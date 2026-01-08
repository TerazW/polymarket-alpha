"""
Tests for Local Recorder - Pro User Local Data Storage (v5.36)
"""

import pytest
import os
import json
import gzip
import tempfile
import shutil
import time
from pathlib import Path
from backend.export.local_recorder import (
    LocalRecorder,
    BatchExporter,
    RecordingConfig,
    RecordingSession,
    RecorderState,
    ExportFormat,
    CompressionType,
    DataType,
    JsonLinesWriter,
    create_recorder,
)


class TestExportFormat:
    """Test ExportFormat enum"""

    def test_format_values(self):
        assert ExportFormat.JSONL.value == "jsonl"
        assert ExportFormat.JSON.value == "json"
        assert ExportFormat.CSV.value == "csv"
        assert ExportFormat.PARQUET.value == "parquet"


class TestCompressionType:
    """Test CompressionType enum"""

    def test_compression_values(self):
        assert CompressionType.NONE.value == "none"
        assert CompressionType.GZIP.value == "gzip"
        assert CompressionType.ZSTD.value == "zstd"


class TestRecorderState:
    """Test RecorderState enum"""

    def test_state_values(self):
        assert RecorderState.IDLE.value == "IDLE"
        assert RecorderState.RECORDING.value == "RECORDING"
        assert RecorderState.PAUSED.value == "PAUSED"
        assert RecorderState.STOPPED.value == "STOPPED"
        assert RecorderState.ERROR.value == "ERROR"


class TestDataType:
    """Test DataType enum"""

    def test_data_types(self):
        assert DataType.RAW_EVENTS.value == "raw_events"
        assert DataType.SHOCKS.value == "shocks"
        assert DataType.REACTIONS.value == "reactions"
        assert DataType.BELIEF_STATES.value == "belief_states"
        assert DataType.ALERTS.value == "alerts"


class TestRecordingConfig:
    """Test RecordingConfig dataclass"""

    def test_config_creation(self):
        config = RecordingConfig(
            output_dir="/tmp/test",
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS, DataType.REACTIONS],
        )
        assert config.output_dir == "/tmp/test"
        assert len(config.token_ids) == 1
        assert len(config.data_types) == 2
        assert config.format == ExportFormat.JSONL
        assert config.compression == CompressionType.GZIP

    def test_config_string_data_types(self):
        """Data types can be passed as strings"""
        config = RecordingConfig(
            output_dir="/tmp/test",
            token_ids=["token_abc"],
            data_types=["shocks", "reactions"],
        )
        assert config.data_types[0] == DataType.SHOCKS
        assert config.data_types[1] == DataType.REACTIONS

    def test_config_custom_settings(self):
        config = RecordingConfig(
            output_dir="/tmp/test",
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
            format=ExportFormat.CSV,
            compression=CompressionType.NONE,
            max_file_size_mb=50,
            buffer_size=500,
        )
        assert config.format == ExportFormat.CSV
        assert config.compression == CompressionType.NONE
        assert config.max_file_size_mb == 50
        assert config.buffer_size == 500


class TestRecordingSession:
    """Test RecordingSession dataclass"""

    def test_session_creation(self):
        config = RecordingConfig(
            output_dir="/tmp/test",
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
        )
        session = RecordingSession(
            session_id="rec_123",
            config=config,
        )
        assert session.session_id == "rec_123"
        assert session.state == RecorderState.IDLE
        assert session.events_recorded == 0

    def test_session_to_dict(self):
        config = RecordingConfig(
            output_dir="/tmp/test",
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
        )
        session = RecordingSession(
            session_id="rec_123",
            config=config,
            state=RecorderState.RECORDING,
            started_at=1000,
            events_recorded=50,
        )
        result = session.to_dict()

        assert result["session_id"] == "rec_123"
        assert result["state"] == "RECORDING"
        assert result["events_recorded"] == 50
        assert "shocks" in result["config"]["data_types"]


class TestJsonLinesWriter:
    """Test JsonLinesWriter"""

    def test_write_uncompressed(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            filepath = f.name

        try:
            writer = JsonLinesWriter(filepath, CompressionType.NONE)
            writer.write({"event": "test", "value": 123})
            writer.write({"event": "test2", "value": 456})
            writer.close()

            # Verify content
            with open(filepath, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2
                assert json.loads(lines[0])["event"] == "test"
                assert json.loads(lines[1])["value"] == 456
        finally:
            os.unlink(filepath)

    def test_write_gzip(self):
        with tempfile.NamedTemporaryFile(suffix='.jsonl.gz', delete=False) as f:
            filepath = f.name

        try:
            writer = JsonLinesWriter(filepath, CompressionType.GZIP)
            writer.write({"event": "compressed", "value": 789})
            writer.close()

            # Verify gzip content
            with gzip.open(filepath, 'rt') as f:
                line = f.readline()
                data = json.loads(line)
                assert data["event"] == "compressed"
        finally:
            os.unlink(filepath)

    def test_bytes_written(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            filepath = f.name

        try:
            writer = JsonLinesWriter(filepath, CompressionType.NONE)
            writer.write({"test": "data"})
            assert writer.get_bytes_written() > 0
            writer.close()
        finally:
            os.unlink(filepath)


class TestLocalRecorder:
    """Test LocalRecorder"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests"""
        dirpath = tempfile.mkdtemp()
        yield dirpath
        shutil.rmtree(dirpath)

    def test_start_recording(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
        )
        recorder = LocalRecorder(config)

        session = recorder.start()

        assert session.state == RecorderState.RECORDING
        assert session.started_at > 0
        assert session.session_id.startswith("rec_")

    def test_record_events(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
            buffer_size=10,  # Small buffer for testing
        )
        recorder = LocalRecorder(config)
        recorder.start()

        # Record some events
        for i in range(5):
            recorder.record({"type": "shock", "data": {"id": i}})

        session = recorder.stop()

        assert session.events_recorded == 5
        assert session.state == RecorderState.STOPPED
        assert len(session.files_created) >= 1

    def test_record_batch(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS, DataType.REACTIONS],
            buffer_size=100,
        )
        recorder = LocalRecorder(config)
        recorder.start()

        events = [
            {"type": "shock", "data": {"id": 1}},
            {"type": "reaction", "data": {"id": 2}},
            {"type": "shock", "data": {"id": 3}},
        ]
        recorded = recorder.record_batch(events)

        session = recorder.stop()

        assert recorded == 3
        assert session.events_recorded == 3

    def test_filter_by_data_type(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],  # Only shocks
            buffer_size=10,
        )
        recorder = LocalRecorder(config)
        recorder.start()

        # Record mixed events
        recorder.record({"type": "shock", "data": {"id": 1}})
        recorder.record({"type": "reaction", "data": {"id": 2}})  # Should be filtered
        recorder.record({"type": "shock", "data": {"id": 3}})

        session = recorder.stop()

        assert session.events_recorded == 2  # Only shocks

    def test_pause_resume(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
            buffer_size=100,
        )
        recorder = LocalRecorder(config)
        session = recorder.start()

        recorder.record({"type": "shock", "data": {"id": 1}})

        recorder.pause()
        assert recorder.session.state == RecorderState.PAUSED

        # Events during pause should not be recorded
        result = recorder.record({"type": "shock", "data": {"id": 2}})
        assert result is False

        recorder.resume()
        assert recorder.session.state == RecorderState.RECORDING

        recorder.record({"type": "shock", "data": {"id": 3}})
        session = recorder.stop()

        assert session.events_recorded == 2  # 1 and 3, not 2

    def test_get_status(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
        )
        recorder = LocalRecorder(config)

        # Status when idle
        status = recorder.get_status()
        assert status["state"] == "IDLE"

        # Status when recording
        recorder.start()
        recorder.record({"type": "shock", "data": {}})
        status = recorder.get_status()

        assert status["state"] == "RECORDING"
        assert "buffer_size" in status

        recorder.stop()

    def test_manifest_created(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
            buffer_size=10,
        )
        recorder = LocalRecorder(config)
        session = recorder.start()
        recorder.record({"type": "shock", "data": {}})
        recorder.stop()

        # Check manifest file exists
        manifest_files = list(Path(temp_dir).glob("*_manifest.json"))
        assert len(manifest_files) == 1

        # Verify manifest content
        with open(manifest_files[0]) as f:
            manifest = json.load(f)
            assert manifest["version"] == "1.0"
            assert manifest["session"]["session_id"] == session.session_id
            assert len(manifest["files"]) >= 1

    def test_uncompressed_output(self, temp_dir):
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
            compression=CompressionType.NONE,
            buffer_size=5,
        )
        recorder = LocalRecorder(config)
        recorder.start()

        for i in range(3):
            recorder.record({"type": "shock", "data": {"id": i}})

        session = recorder.stop()

        # Verify uncompressed JSONL file
        jsonl_files = list(Path(temp_dir).glob("*.jsonl"))
        assert len(jsonl_files) >= 1

        with open(jsonl_files[0]) as f:
            lines = f.readlines()
            assert len(lines) == 3


class TestBatchExporter:
    """Test BatchExporter"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests"""
        dirpath = tempfile.mkdtemp()
        yield dirpath
        shutil.rmtree(dirpath)

    def test_export_demo_mode(self, temp_dir):
        """Test export without database (demo mode)"""
        exporter = BatchExporter(db_connection=None)

        output_path = os.path.join(temp_dir, "shocks.jsonl.gz")
        result = exporter.export_shocks(
            token_id="token_abc",
            start_time=0,
            end_time=int(time.time() * 1000),
            output_path=output_path,
        )

        assert result == output_path
        assert os.path.exists(output_path)

        # Verify content
        with gzip.open(output_path, 'rt') as f:
            data = json.loads(f.readline())
            assert data["demo"] is True

    def test_export_all_demo(self, temp_dir):
        """Test export all data types"""
        exporter = BatchExporter(db_connection=None)

        results = exporter.export_all(
            token_id="token_abc",
            start_time=0,
            end_time=int(time.time() * 1000),
            output_dir=temp_dir,
        )

        assert "shock_events" in results
        assert "reaction_events" in results
        assert "belief_states" in results
        assert "alerts" in results

        # Verify files created
        for table, path in results.items():
            if not path.startswith("ERROR"):
                assert os.path.exists(path)


class TestConvenienceFunctions:
    """Test module-level convenience functions"""

    @pytest.fixture
    def temp_dir(self):
        dirpath = tempfile.mkdtemp()
        yield dirpath
        shutil.rmtree(dirpath)

    def test_create_recorder(self, temp_dir):
        recorder = create_recorder(
            output_dir=temp_dir,
            token_ids=["token_abc", "token_def"],
            data_types=["shocks", "reactions"],
            format="jsonl",
            compression="gzip",
        )

        assert isinstance(recorder, LocalRecorder)
        assert recorder.config.output_dir == temp_dir
        assert len(recorder.config.token_ids) == 2
        assert recorder.config.format == ExportFormat.JSONL

    def test_create_recorder_defaults(self, temp_dir):
        """Create recorder with default data types"""
        recorder = create_recorder(
            output_dir=temp_dir,
            token_ids=["token_abc"],
        )

        # Should include all data types by default
        assert len(recorder.config.data_types) == len(DataType)


class TestIntegration:
    """Integration tests for complete recording workflow"""

    @pytest.fixture
    def temp_dir(self):
        dirpath = tempfile.mkdtemp()
        yield dirpath
        shutil.rmtree(dirpath)

    def test_full_recording_workflow(self, temp_dir):
        """Test complete recording workflow"""
        # Create recorder
        recorder = create_recorder(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=["shocks", "reactions", "alerts"],
        )

        # Start recording
        session = recorder.start()
        assert session.state == RecorderState.RECORDING

        # Simulate recording events
        events = [
            {"type": "shock", "data": {"shock_id": "s1", "magnitude": 0.5}},
            {"type": "reaction", "data": {"reaction_id": "r1", "classification": "HOLD"}},
            {"type": "alert", "data": {"alert_id": "a1", "severity": "HIGH"}},
            {"type": "shock", "data": {"shock_id": "s2", "magnitude": 0.8}},
        ]

        for event in events:
            recorder.record(event)

        # Get status during recording
        status = recorder.get_status()
        assert status["state"] == "RECORDING"

        # Stop recording
        final_session = recorder.stop()

        # Verify results
        assert final_session.state == RecorderState.STOPPED
        assert final_session.events_recorded == 4
        assert final_session.bytes_written > 0
        assert len(final_session.files_created) >= 1

        # Verify manifest
        manifest_path = os.path.join(temp_dir, f"{final_session.session_id}_manifest.json")
        assert os.path.exists(manifest_path)

        with open(manifest_path) as f:
            manifest = json.load(f)
            assert manifest["session"]["events_recorded"] == 4

    def test_recording_with_magnitude_filter(self, temp_dir):
        """Test recording with shock magnitude filter"""
        config = RecordingConfig(
            output_dir=temp_dir,
            token_ids=["token_abc"],
            data_types=[DataType.SHOCKS],
            min_shock_magnitude=0.5,
            buffer_size=10,
        )
        recorder = LocalRecorder(config)
        recorder.start()

        # Record shocks with different magnitudes
        recorder.record({"type": "shock", "data": {"id": 1, "magnitude": 0.3}})  # Filtered
        recorder.record({"type": "shock", "data": {"id": 2, "magnitude": 0.6}})  # Recorded
        recorder.record({"type": "shock", "data": {"id": 3, "magnitude": 0.8}})  # Recorded

        session = recorder.stop()

        assert session.events_recorded == 2
