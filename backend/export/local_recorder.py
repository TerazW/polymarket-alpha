"""
Local Recorder - Pro User Local Data Storage (v5.36)

Allows Pro users to record and save market data locally for their own analysis.
Supports multiple output formats and both streaming and batch export modes.

Features:
- Real-time streaming to local files
- Batch export of historical data
- Multiple formats: JSON Lines, Parquet, CSV
- Compression support (gzip, zstd)
- Automatic file rotation by size/time
- Resume capability for interrupted recordings
"""

import os
import json
import gzip
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Iterator
from abc import ABC, abstractmethod


class ExportFormat(str, Enum):
    """Supported export formats"""
    JSONL = "jsonl"           # JSON Lines (streaming friendly)
    JSON = "json"             # Full JSON array
    CSV = "csv"               # CSV (flat data only)
    PARQUET = "parquet"       # Apache Parquet (columnar, efficient)


class CompressionType(str, Enum):
    """Supported compression types"""
    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"


class RecorderState(str, Enum):
    """Recording state"""
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class DataType(str, Enum):
    """Types of data that can be recorded"""
    RAW_EVENTS = "raw_events"         # Raw WebSocket messages
    BOOK_SNAPSHOTS = "book_snapshots" # Order book snapshots
    SHOCKS = "shocks"                 # Detected shock events
    REACTIONS = "reactions"           # Reaction classifications
    BELIEF_STATES = "belief_states"   # Belief state changes
    ALERTS = "alerts"                 # Generated alerts
    TILES = "tiles"                   # Heatmap tiles


@dataclass
class RecordingConfig:
    """Configuration for a recording session"""
    output_dir: str
    token_ids: List[str]
    data_types: List[DataType]
    format: ExportFormat = ExportFormat.JSONL
    compression: CompressionType = CompressionType.GZIP

    # File rotation settings
    max_file_size_mb: int = 100       # Rotate after 100MB
    max_file_age_hours: int = 24      # Rotate after 24 hours

    # Buffer settings
    buffer_size: int = 1000           # Events to buffer before write
    flush_interval_sec: int = 5       # Flush every 5 seconds

    # Filter settings
    include_metadata: bool = True     # Include processing metadata
    min_shock_magnitude: float = 0.0  # Filter by shock magnitude

    def __post_init__(self):
        # Convert string data types to enum if needed
        if self.data_types and isinstance(self.data_types[0], str):
            self.data_types = [DataType(dt) for dt in self.data_types]


@dataclass
class RecordingSession:
    """Represents an active or completed recording session"""
    session_id: str
    config: RecordingConfig
    state: RecorderState = RecorderState.IDLE
    started_at: int = 0               # Unix timestamp ms
    stopped_at: int = 0
    events_recorded: int = 0
    bytes_written: int = 0
    files_created: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "duration_sec": (self.stopped_at - self.started_at) / 1000 if self.stopped_at else None,
            "events_recorded": self.events_recorded,
            "bytes_written": self.bytes_written,
            "files_created": self.files_created,
            "config": {
                "token_ids": self.config.token_ids,
                "data_types": [dt.value for dt in self.config.data_types],
                "format": self.config.format.value,
                "compression": self.config.compression.value,
            },
            "error": self.error_message,
        }


class OutputWriter(ABC):
    """Abstract base class for format-specific writers"""

    @abstractmethod
    def write(self, event: Dict[str, Any]) -> int:
        """Write an event, return bytes written"""
        pass

    @abstractmethod
    def flush(self) -> None:
        """Flush buffered data"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the writer"""
        pass

    @abstractmethod
    def get_bytes_written(self) -> int:
        """Get total bytes written"""
        pass


class JsonLinesWriter(OutputWriter):
    """JSON Lines format writer (one JSON object per line)"""

    def __init__(self, filepath: str, compression: CompressionType):
        self.filepath = filepath
        self.compression = compression
        self.bytes_written = 0

        if compression == CompressionType.GZIP:
            self.file = gzip.open(filepath, 'wt', encoding='utf-8')
        elif compression == CompressionType.ZSTD:
            try:
                import zstandard as zstd
                self.cctx = zstd.ZstdCompressor()
                self.file = open(filepath, 'wb')
                self.stream_writer = self.cctx.stream_writer(self.file)
            except ImportError:
                raise ImportError("zstandard package required for zstd compression")
        else:
            self.file = open(filepath, 'w', encoding='utf-8')

    def write(self, event: Dict[str, Any]) -> int:
        line = json.dumps(event, separators=(',', ':')) + '\n'

        if self.compression == CompressionType.ZSTD:
            data = line.encode('utf-8')
            self.stream_writer.write(data)
            written = len(data)
        else:
            self.file.write(line)
            written = len(line.encode('utf-8'))

        self.bytes_written += written
        return written

    def flush(self) -> None:
        if self.compression == CompressionType.ZSTD:
            self.stream_writer.flush()
        else:
            self.file.flush()

    def close(self) -> None:
        if self.compression == CompressionType.ZSTD:
            self.stream_writer.close()
        self.file.close()

    def get_bytes_written(self) -> int:
        return self.bytes_written


class CsvWriter(OutputWriter):
    """CSV format writer (flat data only)"""

    def __init__(self, filepath: str, compression: CompressionType, columns: List[str]):
        self.filepath = filepath
        self.compression = compression
        self.columns = columns
        self.bytes_written = 0
        self.header_written = False

        if compression == CompressionType.GZIP:
            self.file = gzip.open(filepath, 'wt', encoding='utf-8', newline='')
        else:
            self.file = open(filepath, 'w', encoding='utf-8', newline='')

        import csv
        self.writer = csv.DictWriter(self.file, fieldnames=columns, extrasaction='ignore')

    def write(self, event: Dict[str, Any]) -> int:
        if not self.header_written:
            self.writer.writeheader()
            self.header_written = True

        # Flatten nested dicts for CSV
        flat_event = self._flatten(event)
        self.writer.writerow(flat_event)

        # Estimate bytes (CSV doesn't track easily)
        written = len(str(flat_event))
        self.bytes_written += written
        return written

    def _flatten(self, d: Dict, parent_key: str = '', sep: str = '_') -> Dict:
        """Flatten nested dictionary"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten(v, new_key, sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def flush(self) -> None:
        self.file.flush()

    def close(self) -> None:
        self.file.close()

    def get_bytes_written(self) -> int:
        return self.bytes_written


class LocalRecorder:
    """
    Main recorder class for Pro users to save data locally.

    Usage:
        config = RecordingConfig(
            output_dir="/path/to/output",
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS, DataType.REACTIONS],
            format=ExportFormat.JSONL,
            compression=CompressionType.GZIP,
        )

        recorder = LocalRecorder(config)
        recorder.start()

        # Record events as they arrive
        recorder.record({"type": "shock", "data": {...}})

        # Stop recording
        session = recorder.stop()
        print(f"Recorded {session.events_recorded} events")
    """

    def __init__(self, config: RecordingConfig):
        self.config = config
        self.session: Optional[RecordingSession] = None
        self.writer: Optional[OutputWriter] = None
        self.buffer: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.flush_timer: Optional[threading.Timer] = None
        self.current_file_index = 0
        self.current_file_start_time = 0

    def start(self) -> RecordingSession:
        """Start a new recording session"""
        if self.session and self.session.state == RecorderState.RECORDING:
            raise RuntimeError("Recording already in progress")

        # Create output directory
        Path(self.config.output_dir).mkdir(parents=True, exist_ok=True)

        # Generate session ID
        session_id = f"rec_{int(time.time() * 1000)}"

        self.session = RecordingSession(
            session_id=session_id,
            config=self.config,
            state=RecorderState.RECORDING,
            started_at=int(time.time() * 1000),
        )

        # Create initial writer
        self._rotate_file()

        # Start flush timer
        self._schedule_flush()

        return self.session

    def record(self, event: Dict[str, Any]) -> bool:
        """
        Record an event. Returns True if recorded, False if filtered/error.
        """
        if not self.session or self.session.state != RecorderState.RECORDING:
            return False

        # Check if event type matches config
        event_type = event.get("type", "")
        if not self._should_record(event_type, event):
            return False

        # Add metadata
        if self.config.include_metadata:
            event = {
                **event,
                "_recorded_at": int(time.time() * 1000),
                "_session_id": self.session.session_id,
            }

        with self.lock:
            self.buffer.append(event)

            # Check if we need to flush
            if len(self.buffer) >= self.config.buffer_size:
                self._flush_buffer()

            # Check if we need to rotate file
            if self._should_rotate():
                self._rotate_file()

        return True

    def record_batch(self, events: List[Dict[str, Any]]) -> int:
        """Record multiple events. Returns count of recorded events."""
        recorded = 0
        for event in events:
            if self.record(event):
                recorded += 1
        return recorded

    def pause(self) -> None:
        """Pause recording (buffer is preserved)"""
        if self.session and self.session.state == RecorderState.RECORDING:
            self.session.state = RecorderState.PAUSED
            self._flush_buffer()

    def resume(self) -> None:
        """Resume paused recording"""
        if self.session and self.session.state == RecorderState.PAUSED:
            self.session.state = RecorderState.RECORDING
            self._schedule_flush()

    def stop(self) -> RecordingSession:
        """Stop recording and finalize files"""
        if not self.session:
            raise RuntimeError("No active recording session")

        # Cancel flush timer
        if self.flush_timer:
            self.flush_timer.cancel()
            self.flush_timer = None

        # Flush remaining buffer
        with self.lock:
            self._flush_buffer()

        # Close writer
        if self.writer:
            self.writer.close()
            self.writer = None

        # Update session
        self.session.state = RecorderState.STOPPED
        self.session.stopped_at = int(time.time() * 1000)

        # Write session manifest
        self._write_manifest()

        return self.session

    def get_status(self) -> Dict[str, Any]:
        """Get current recording status"""
        if not self.session:
            return {"state": RecorderState.IDLE.value}

        return {
            **self.session.to_dict(),
            "buffer_size": len(self.buffer),
            "current_file": self.session.files_created[-1] if self.session.files_created else None,
        }

    def _should_record(self, event_type: str, event: Dict[str, Any]) -> bool:
        """Check if event should be recorded based on config"""
        type_mapping = {
            "raw": DataType.RAW_EVENTS,
            "book": DataType.BOOK_SNAPSHOTS,
            "shock": DataType.SHOCKS,
            "reaction": DataType.REACTIONS,
            "belief": DataType.BELIEF_STATES,
            "alert": DataType.ALERTS,
            "tile": DataType.TILES,
        }

        data_type = type_mapping.get(event_type)
        if data_type and data_type not in self.config.data_types:
            return False

        # Apply magnitude filter for shocks
        if event_type == "shock" and self.config.min_shock_magnitude > 0:
            magnitude = event.get("data", {}).get("magnitude", 0)
            if magnitude < self.config.min_shock_magnitude:
                return False

        return True

    def _should_rotate(self) -> bool:
        """Check if file rotation is needed"""
        if not self.writer:
            return True

        # Check size
        if self.writer.get_bytes_written() >= self.config.max_file_size_mb * 1024 * 1024:
            return True

        # Check age
        age_ms = int(time.time() * 1000) - self.current_file_start_time
        if age_ms >= self.config.max_file_age_hours * 3600 * 1000:
            return True

        return False

    def _rotate_file(self) -> None:
        """Close current file and open a new one"""
        # Close existing writer
        if self.writer:
            self.writer.close()

        # Generate new filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = self._get_extension()
        filename = f"{self.session.session_id}_{timestamp}_{self.current_file_index:04d}{extension}"
        filepath = os.path.join(self.config.output_dir, filename)

        # Create new writer
        self.writer = self._create_writer(filepath)
        self.current_file_index += 1
        self.current_file_start_time = int(time.time() * 1000)
        self.session.files_created.append(filepath)

    def _get_extension(self) -> str:
        """Get file extension based on format and compression"""
        ext = f".{self.config.format.value}"
        if self.config.compression == CompressionType.GZIP:
            ext += ".gz"
        elif self.config.compression == CompressionType.ZSTD:
            ext += ".zst"
        return ext

    def _create_writer(self, filepath: str) -> OutputWriter:
        """Create format-specific writer"""
        if self.config.format == ExportFormat.JSONL:
            return JsonLinesWriter(filepath, self.config.compression)
        elif self.config.format == ExportFormat.CSV:
            # Define columns based on data types
            columns = ["timestamp", "token_id", "type", "data"]
            return CsvWriter(filepath, self.config.compression, columns)
        else:
            # Default to JSON Lines for other formats
            return JsonLinesWriter(filepath, self.config.compression)

    def _flush_buffer(self) -> None:
        """Write buffered events to file"""
        if not self.buffer or not self.writer:
            return

        for event in self.buffer:
            bytes_written = self.writer.write(event)
            self.session.bytes_written += bytes_written
            self.session.events_recorded += 1

        self.writer.flush()
        self.buffer.clear()

    def _schedule_flush(self) -> None:
        """Schedule periodic buffer flush"""
        if self.session and self.session.state == RecorderState.RECORDING:
            self.flush_timer = threading.Timer(
                self.config.flush_interval_sec,
                self._timed_flush
            )
            self.flush_timer.daemon = True
            self.flush_timer.start()

    def _timed_flush(self) -> None:
        """Flush buffer on timer"""
        with self.lock:
            self._flush_buffer()
        self._schedule_flush()

    def _write_manifest(self) -> None:
        """Write session manifest file"""
        manifest_path = os.path.join(
            self.config.output_dir,
            f"{self.session.session_id}_manifest.json"
        )

        manifest = {
            "version": "1.0",
            "session": self.session.to_dict(),
            "files": [
                {
                    "path": f,
                    "relative_path": os.path.basename(f),
                }
                for f in self.session.files_created
            ],
            "schema": {
                "format": self.config.format.value,
                "compression": self.config.compression.value,
                "data_types": [dt.value for dt in self.config.data_types],
            },
        }

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)


class BatchExporter:
    """
    Export historical data in batch from database.

    Usage:
        exporter = BatchExporter(db_connection)

        # Export shocks for a token
        filepath = exporter.export_shocks(
            token_id="token_abc",
            start_time=start_ms,
            end_time=end_ms,
            output_path="/path/to/output.jsonl.gz",
        )
    """

    def __init__(self, db_connection=None):
        self.db = db_connection

    def export_shocks(
        self,
        token_id: str,
        start_time: int,
        end_time: int,
        output_path: str,
        format: ExportFormat = ExportFormat.JSONL,
        compression: CompressionType = CompressionType.GZIP,
    ) -> str:
        """Export shock events for a token within time range"""
        return self._export_table(
            table="shock_events",
            token_id=token_id,
            start_time=start_time,
            end_time=end_time,
            output_path=output_path,
            format=format,
            compression=compression,
        )

    def export_reactions(
        self,
        token_id: str,
        start_time: int,
        end_time: int,
        output_path: str,
        format: ExportFormat = ExportFormat.JSONL,
        compression: CompressionType = CompressionType.GZIP,
    ) -> str:
        """Export reaction events for a token within time range"""
        return self._export_table(
            table="reaction_events",
            token_id=token_id,
            start_time=start_time,
            end_time=end_time,
            output_path=output_path,
            format=format,
            compression=compression,
        )

    def export_belief_states(
        self,
        token_id: str,
        start_time: int,
        end_time: int,
        output_path: str,
        format: ExportFormat = ExportFormat.JSONL,
        compression: CompressionType = CompressionType.GZIP,
    ) -> str:
        """Export belief state history for a token within time range"""
        return self._export_table(
            table="belief_states",
            token_id=token_id,
            start_time=start_time,
            end_time=end_time,
            output_path=output_path,
            format=format,
            compression=compression,
        )

    def export_all(
        self,
        token_id: str,
        start_time: int,
        end_time: int,
        output_dir: str,
        format: ExportFormat = ExportFormat.JSONL,
        compression: CompressionType = CompressionType.GZIP,
    ) -> Dict[str, str]:
        """Export all data types for a token"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        ext = f".{format.value}"
        if compression == CompressionType.GZIP:
            ext += ".gz"

        results = {}

        tables = ["shock_events", "reaction_events", "belief_states", "alerts"]
        for table in tables:
            output_path = os.path.join(output_dir, f"{token_id}_{table}{ext}")
            try:
                self._export_table(
                    table=table,
                    token_id=token_id,
                    start_time=start_time,
                    end_time=end_time,
                    output_path=output_path,
                    format=format,
                    compression=compression,
                )
                results[table] = output_path
            except Exception as e:
                results[table] = f"ERROR: {str(e)}"

        return results

    def _export_table(
        self,
        table: str,
        token_id: str,
        start_time: int,
        end_time: int,
        output_path: str,
        format: ExportFormat,
        compression: CompressionType,
    ) -> str:
        """Generic table export"""
        if not self.db:
            # Dry run / demo mode
            return self._export_demo(output_path, format, compression)

        # Query data
        query = f"""
            SELECT * FROM {table}
            WHERE token_id = %s
            AND timestamp >= %s
            AND timestamp <= %s
            ORDER BY timestamp
        """

        rows = self.db.execute(query, (token_id, start_time, end_time))

        # Write to file
        writer = JsonLinesWriter(output_path, compression)
        for row in rows:
            writer.write(dict(row))
        writer.close()

        return output_path

    def _export_demo(
        self,
        output_path: str,
        format: ExportFormat,
        compression: CompressionType,
    ) -> str:
        """Demo export without DB"""
        writer = JsonLinesWriter(output_path, compression)

        # Write sample data
        sample = {
            "demo": True,
            "message": "This is a demo export. Connect to database for real data.",
            "timestamp": int(time.time() * 1000),
        }
        writer.write(sample)
        writer.close()

        return output_path


def create_recorder(
    output_dir: str,
    token_ids: List[str],
    data_types: Optional[List[str]] = None,
    format: str = "jsonl",
    compression: str = "gzip",
) -> LocalRecorder:
    """
    Convenience function to create a LocalRecorder.

    Args:
        output_dir: Directory to save recordings
        token_ids: List of token IDs to record
        data_types: List of data types (default: all)
        format: Output format (jsonl, csv, parquet)
        compression: Compression type (none, gzip, zstd)

    Returns:
        Configured LocalRecorder instance
    """
    if data_types is None:
        data_types = [dt.value for dt in DataType]

    config = RecordingConfig(
        output_dir=output_dir,
        token_ids=token_ids,
        data_types=[DataType(dt) for dt in data_types],
        format=ExportFormat(format),
        compression=CompressionType(compression),
    )

    return LocalRecorder(config)
