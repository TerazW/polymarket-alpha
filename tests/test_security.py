"""
Tests for Security Module (v5.23)

Validates:
1. API Key authentication
2. Access Control Lists (ACL)
3. Audit logging

"安全是底线"
"""

import pytest
import time

from backend.security.auth import (
    generate_api_key,
    hash_api_key,
    APIKey,
    APIKeyManager,
    AuthResult,
    AuthStatus,
    authenticate_request,
    API_KEY_PREFIX,
)

from backend.security.acl import (
    Permission,
    Role,
    ROLE_PERMISSIONS,
    ACLEntry,
    ACLManager,
    check_permission,
    get_role_permissions,
    get_all_permissions_for_roles,
)

from backend.security.audit import (
    AuditAction,
    AuditEntry,
    AuditLogger,
    get_audit_logger,
    audit_log,
)


class TestAPIKeyGeneration:
    """Test API key generation and hashing"""

    def test_generate_api_key_format(self):
        """Generated key should have correct prefix"""
        key = generate_api_key()

        assert key.startswith(API_KEY_PREFIX)
        assert len(key) == len(API_KEY_PREFIX) + 32

    def test_generate_api_key_unique(self):
        """Generated keys should be unique"""
        keys = [generate_api_key() for _ in range(100)]

        assert len(set(keys)) == 100

    def test_hash_api_key_deterministic(self):
        """Same key should produce same hash"""
        key = generate_api_key()

        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_hash_api_key_different_keys(self):
        """Different keys should produce different hashes"""
        key1 = generate_api_key()
        key2 = generate_api_key()

        assert hash_api_key(key1) != hash_api_key(key2)


class TestAPIKey:
    """Test APIKey dataclass"""

    def test_api_key_creation(self):
        """Should create APIKey with all fields"""
        now = int(time.time() * 1000)
        key = APIKey(
            key_id="key_001",
            key_hash="abc123",
            name="Test Key",
            created_at=now,
            roles=["reader"],
        )

        assert key.key_id == "key_001"
        assert key.name == "Test Key"
        assert key.enabled is True

    def test_is_expired_no_expiry(self):
        """Key without expiry should never expire"""
        key = APIKey(
            key_id="key_001",
            key_hash="abc123",
            name="Test",
            created_at=int(time.time() * 1000),
            expires_at=None,
        )

        assert key.is_expired() is False

    def test_is_expired_future(self):
        """Key with future expiry should not be expired"""
        key = APIKey(
            key_id="key_001",
            key_hash="abc123",
            name="Test",
            created_at=int(time.time() * 1000),
            expires_at=int(time.time() * 1000) + 100000,
        )

        assert key.is_expired() is False

    def test_is_expired_past(self):
        """Key with past expiry should be expired"""
        key = APIKey(
            key_id="key_001",
            key_hash="abc123",
            name="Test",
            created_at=int(time.time() * 1000) - 200000,
            expires_at=int(time.time() * 1000) - 100000,
        )

        assert key.is_expired() is True

    def test_is_valid_enabled(self):
        """Enabled non-expired key should be valid"""
        key = APIKey(
            key_id="key_001",
            key_hash="abc123",
            name="Test",
            created_at=int(time.time() * 1000),
            enabled=True,
        )

        assert key.is_valid() is True

    def test_is_valid_disabled(self):
        """Disabled key should not be valid"""
        key = APIKey(
            key_id="key_001",
            key_hash="abc123",
            name="Test",
            created_at=int(time.time() * 1000),
            enabled=False,
        )

        assert key.is_valid() is False

    def test_to_dict(self):
        """Should serialize to dict without hash by default"""
        key = APIKey(
            key_id="key_001",
            key_hash="secret_hash",
            name="Test",
            created_at=1000,
            roles=["reader"],
        )

        d = key.to_dict()

        assert d["key_id"] == "key_001"
        assert d["name"] == "Test"
        assert "key_hash" not in d

    def test_to_dict_with_hash(self):
        """Should include hash when requested"""
        key = APIKey(
            key_id="key_001",
            key_hash="secret_hash",
            name="Test",
            created_at=1000,
        )

        d = key.to_dict(include_hash=True)

        assert d["key_hash"] == "secret_hash"


class TestAPIKeyManager:
    """Test APIKeyManager"""

    def test_create_key(self):
        """Should create new key"""
        manager = APIKeyManager()

        raw_key, key_record = manager.create_key(
            name="Test Key",
            roles=["reader"],
        )

        assert raw_key.startswith(API_KEY_PREFIX)
        assert key_record.name == "Test Key"
        assert "reader" in key_record.roles

    def test_create_key_with_expiry(self):
        """Should set expiry correctly"""
        manager = APIKeyManager()

        raw_key, key_record = manager.create_key(
            name="Test",
            expires_in_days=30,
        )

        assert key_record.expires_at is not None
        # Should expire roughly 30 days from now
        expected = int(time.time() * 1000) + (30 * 24 * 60 * 60 * 1000)
        assert abs(key_record.expires_at - expected) < 1000

    def test_validate_key_success(self):
        """Should validate correct key"""
        manager = APIKeyManager()
        raw_key, _ = manager.create_key(name="Test")

        result = manager.validate_key(raw_key)

        assert result is not None
        assert result.name == "Test"

    def test_validate_key_invalid(self):
        """Should reject invalid key"""
        manager = APIKeyManager()

        result = manager.validate_key("brm_invalid_key_12345678901234567890")

        assert result is None

    def test_validate_key_wrong_prefix(self):
        """Should reject key without correct prefix"""
        manager = APIKeyManager()

        result = manager.validate_key("wrong_prefix_key")

        assert result is None

    def test_validate_key_updates_last_used(self):
        """Validating should update last_used_at"""
        manager = APIKeyManager()
        raw_key, key_record = manager.create_key(name="Test")

        assert key_record.last_used_at is None

        manager.validate_key(raw_key)

        assert key_record.last_used_at is not None

    def test_revoke_key(self):
        """Should disable revoked key"""
        manager = APIKeyManager()
        raw_key, key_record = manager.create_key(name="Test")

        result = manager.revoke_key(key_record.key_id)

        assert result is True
        assert key_record.enabled is False
        assert key_record.is_valid() is False

    def test_delete_key(self):
        """Should remove deleted key"""
        manager = APIKeyManager()
        raw_key, key_record = manager.create_key(name="Test")
        key_id = key_record.key_id

        result = manager.delete_key(key_id)

        assert result is True
        assert manager.get_key(key_id) is None
        assert manager.validate_key(raw_key) is None

    def test_list_keys(self):
        """Should list all enabled keys"""
        manager = APIKeyManager()
        manager.create_key(name="Key1")
        _, key2 = manager.create_key(name="Key2")
        manager.create_key(name="Key3")

        manager.revoke_key(key2.key_id)

        keys = manager.list_keys()

        assert len(keys) == 2
        assert all(k.enabled for k in keys)

    def test_update_roles(self):
        """Should update key roles"""
        manager = APIKeyManager()
        _, key_record = manager.create_key(name="Test", roles=["reader"])

        manager.update_roles(key_record.key_id, ["reader", "writer"])

        assert "writer" in key_record.roles


class TestAuthentication:
    """Test authenticate_request function"""

    def test_missing_key(self):
        """Should reject missing key"""
        manager = APIKeyManager()

        result = authenticate_request(None, manager)

        assert result.status == AuthStatus.MISSING_KEY
        assert result.is_authenticated is False

    def test_invalid_key(self):
        """Should reject invalid key"""
        manager = APIKeyManager()

        result = authenticate_request("brm_invalid", manager)

        assert result.status == AuthStatus.INVALID_KEY

    def test_expired_key(self):
        """Should reject expired key"""
        manager = APIKeyManager()
        raw_key, key_record = manager.create_key(name="Test")
        # Manually expire it
        key_record.expires_at = int(time.time() * 1000) - 1000

        result = authenticate_request(raw_key, manager)

        assert result.status == AuthStatus.EXPIRED_KEY

    def test_disabled_key(self):
        """Should reject disabled key"""
        manager = APIKeyManager()
        raw_key, key_record = manager.create_key(name="Test")
        manager.revoke_key(key_record.key_id)

        result = authenticate_request(raw_key, manager)

        assert result.status == AuthStatus.DISABLED_KEY

    def test_success(self):
        """Should authenticate valid key"""
        manager = APIKeyManager()
        raw_key, key_record = manager.create_key(name="Test", roles=["reader"])

        result = authenticate_request(raw_key, manager)

        assert result.status == AuthStatus.SUCCESS
        assert result.is_authenticated is True
        assert result.key.key_id == key_record.key_id

    def test_required_roles_success(self):
        """Should pass with matching role"""
        manager = APIKeyManager()
        raw_key, _ = manager.create_key(name="Test", roles=["reader"])

        result = authenticate_request(raw_key, manager, required_roles=["reader"])

        assert result.status == AuthStatus.SUCCESS

    def test_required_roles_failure(self):
        """Should fail without matching role"""
        manager = APIKeyManager()
        raw_key, _ = manager.create_key(name="Test", roles=["reader"])

        result = authenticate_request(raw_key, manager, required_roles=["admin"])

        assert result.status == AuthStatus.INSUFFICIENT_PERMISSIONS


class TestPermission:
    """Test Permission enum"""

    def test_permission_values(self):
        """Permissions should have expected values"""
        assert Permission.RADAR_READ.value == "radar:read"
        assert Permission.ALERTS_ACK.value == "alerts:ack"
        assert Permission.ADMIN_KEYS.value == "admin:keys"
        assert Permission.ALL.value == "*"


class TestRole:
    """Test Role enum and permissions"""

    def test_viewer_permissions(self):
        """Viewer should have read-only permissions"""
        perms = ROLE_PERMISSIONS[Role.VIEWER]

        assert Permission.RADAR_READ in perms
        assert Permission.EVIDENCE_READ in perms
        assert Permission.ALERTS_ACK not in perms
        assert Permission.ADMIN_KEYS not in perms

    def test_operator_permissions(self):
        """Operator should have alert management"""
        perms = ROLE_PERMISSIONS[Role.OPERATOR]

        assert Permission.ALERTS_ACK in perms
        assert Permission.ALERTS_RESOLVE in perms

    def test_admin_permissions(self):
        """Admin should have wildcard access"""
        perms = ROLE_PERMISSIONS[Role.ADMIN]

        assert Permission.ALL in perms

    def test_get_role_permissions(self):
        """Should get permissions for role name"""
        perms = get_role_permissions("viewer")

        assert Permission.RADAR_READ in perms

    def test_get_role_permissions_invalid(self):
        """Should return empty set for invalid role"""
        perms = get_role_permissions("nonexistent")

        assert len(perms) == 0

    def test_get_all_permissions_for_roles(self):
        """Should combine permissions from multiple roles"""
        perms = get_all_permissions_for_roles(["viewer", "operator"])

        assert Permission.RADAR_READ in perms  # From viewer
        assert Permission.ALERTS_ACK in perms  # From operator


class TestACLEntry:
    """Test ACLEntry dataclass"""

    def test_entry_creation(self):
        """Should create entry with all fields"""
        entry = ACLEntry(
            entry_id="acl_001",
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
            resource_pattern="token:*",
        )

        assert entry.entry_id == "acl_001"
        assert entry.permission == "alerts:ack"

    def test_matches_permission_exact(self):
        """Should match exact permission"""
        entry = ACLEntry(
            entry_id="acl_001",
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        assert entry.matches_permission("alerts:ack") is True
        assert entry.matches_permission("alerts:resolve") is False

    def test_matches_permission_wildcard(self):
        """Should match with wildcard"""
        entry = ACLEntry(
            entry_id="acl_001",
            subject_type="key",
            subject_id="key_abc",
            permission="*",
        )

        assert entry.matches_permission("alerts:ack") is True
        assert entry.matches_permission("admin:keys") is True

    def test_matches_resource_exact(self):
        """Should match exact resource"""
        entry = ACLEntry(
            entry_id="acl_001",
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
            resource_pattern="token:abc123",
        )

        assert entry.matches_resource("token:abc123") is True
        assert entry.matches_resource("token:xyz") is False

    def test_matches_resource_pattern(self):
        """Should match resource pattern"""
        entry = ACLEntry(
            entry_id="acl_001",
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
            resource_pattern="token:abc*",
        )

        assert entry.matches_resource("token:abc123") is True
        assert entry.matches_resource("token:abcdef") is True
        assert entry.matches_resource("token:xyz") is False


class TestACLManager:
    """Test ACLManager"""

    def test_grant_permission(self):
        """Should grant permission"""
        acl = ACLManager()

        entry = acl.grant(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        assert entry.entry_id is not None
        assert entry.permission == "alerts:ack"

    def test_check_permission_granted(self):
        """Should find granted permission"""
        acl = ACLManager()
        acl.grant(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        result = acl.check(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        assert result is True

    def test_check_permission_not_granted(self):
        """Should not find non-granted permission"""
        acl = ACLManager()

        result = acl.check(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        assert result is False

    def test_revoke_permission(self):
        """Should revoke permission"""
        acl = ACLManager()
        entry = acl.grant(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        acl.revoke(entry.entry_id)

        result = acl.check(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )
        assert result is False

    def test_expired_entry(self):
        """Should not honor expired entries"""
        acl = ACLManager()
        acl.grant(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
            expires_at=int(time.time() * 1000) - 1000,  # Already expired
        )

        result = acl.check(
            subject_type="key",
            subject_id="key_abc",
            permission="alerts:ack",
        )

        assert result is False


class TestCheckPermission:
    """Test check_permission utility function"""

    def test_role_grants_permission(self):
        """Role should grant its permissions"""
        result = check_permission(
            roles=["viewer"],
            required_permission="radar:read",
        )

        assert result is True

    def test_role_denies_permission(self):
        """Role should deny non-granted permissions"""
        result = check_permission(
            roles=["viewer"],
            required_permission="admin:keys",
        )

        assert result is False

    def test_admin_grants_all(self):
        """Admin role should grant all permissions"""
        result = check_permission(
            roles=["admin"],
            required_permission="admin:keys",
        )

        assert result is True

    def test_acl_grants_permission(self):
        """ACL should grant additional permissions"""
        acl = ACLManager()
        acl.grant(
            subject_type="key",
            subject_id="key_abc",
            permission="admin:keys",
        )

        result = check_permission(
            roles=["viewer"],
            required_permission="admin:keys",
            acl_manager=acl,
            subject_type="key",
            subject_id="key_abc",
        )

        assert result is True


class TestAuditAction:
    """Test AuditAction enum"""

    def test_action_values(self):
        """Actions should have expected format"""
        assert AuditAction.AUTH_LOGIN.value == "auth.login"
        assert AuditAction.ALERT_ACK.value == "alert.ack"
        assert AuditAction.ADMIN_CONFIG_CHANGE.value == "admin.config_change"


class TestAuditEntry:
    """Test AuditEntry dataclass"""

    def test_entry_creation(self):
        """Should create entry with all fields"""
        entry = AuditEntry(
            entry_id="",
            timestamp=1000,
            action=AuditAction.ALERT_ACK,
            actor_type="key",
            actor_id="key_abc",
            resource_type="alert",
            resource_id="alert-123",
        )

        assert entry.action == AuditAction.ALERT_ACK
        assert entry.entry_id != ""  # Auto-generated

    def test_to_dict(self):
        """Should serialize to dict"""
        entry = AuditEntry(
            entry_id="audit_001",
            timestamp=1000,
            action=AuditAction.ALERT_ACK,
            actor_type="key",
            actor_id="key_abc",
        )

        d = entry.to_dict()

        assert d["entry_id"] == "audit_001"
        assert d["action"] == "alert.ack"
        assert d["actor_id"] == "key_abc"

    def test_to_json(self):
        """Should serialize to JSON string"""
        entry = AuditEntry(
            entry_id="audit_001",
            timestamp=1000,
            action=AuditAction.AUTH_LOGIN,
            actor_type="user",
            actor_id="user_123",
        )

        json_str = entry.to_json()

        assert '"action": "auth.login"' in json_str


class TestAuditLogger:
    """Test AuditLogger"""

    def test_logger_creation(self):
        """Should create logger"""
        logger = AuditLogger(max_entries=100)

        assert logger.max_entries == 100

    def test_log_entry(self):
        """Should log entry"""
        logger = AuditLogger()

        entry = logger.log(
            action=AuditAction.ALERT_ACK,
            actor_type="key",
            actor_id="key_abc",
            resource_type="alert",
            resource_id="alert-123",
        )

        assert entry.entry_id is not None
        assert entry.timestamp > 0

    def test_query_by_action(self):
        """Should query by action"""
        logger = AuditLogger()

        logger.log(action=AuditAction.ALERT_ACK, actor_id="key1")
        logger.log(action=AuditAction.AUTH_LOGIN, actor_id="key2")
        logger.log(action=AuditAction.ALERT_ACK, actor_id="key3")

        results = logger.query(action=AuditAction.ALERT_ACK)

        assert len(results) == 2

    def test_query_by_actor(self):
        """Should query by actor"""
        logger = AuditLogger()

        logger.log(action=AuditAction.ALERT_ACK, actor_id="key_abc")
        logger.log(action=AuditAction.AUTH_LOGIN, actor_id="key_abc")
        logger.log(action=AuditAction.ALERT_ACK, actor_id="key_xyz")

        results = logger.query(actor_id="key_abc")

        assert len(results) == 2

    def test_query_pagination(self):
        """Should support pagination"""
        logger = AuditLogger()

        for i in range(10):
            logger.log(action=AuditAction.API_REQUEST, actor_id=f"key_{i}")

        page1 = logger.query(limit=3, offset=0)
        page2 = logger.query(limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].actor_id != page2[0].actor_id

    def test_max_entries_limit(self):
        """Should respect max entries limit"""
        logger = AuditLogger(max_entries=5)

        for i in range(10):
            logger.log(action=AuditAction.API_REQUEST, actor_id=f"key_{i}")

        results = logger.get_recent(limit=100)

        assert len(results) == 5

    def test_get_stats(self):
        """Should return statistics"""
        logger = AuditLogger()

        logger.log(action=AuditAction.ALERT_ACK, result="success")
        logger.log(action=AuditAction.ALERT_ACK, result="success")
        logger.log(action=AuditAction.AUTH_FAILED, result="failure")

        stats = logger.get_stats()

        assert stats["total_logged"] == 3
        assert stats["by_action"]["alert.ack"] == 2
        assert stats["by_result"]["success"] == 2
        assert stats["by_result"]["failure"] == 1

    def test_sink_callback(self):
        """Should call sink callback"""
        received = []

        def sink(entry):
            received.append(entry)

        logger = AuditLogger(sink=sink)

        logger.log(action=AuditAction.AUTH_LOGIN, actor_id="test")

        assert len(received) == 1
        assert received[0].actor_id == "test"


class TestGlobalAuditLogger:
    """Test global audit logger singleton"""

    def test_singleton(self):
        """Should return same instance"""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()

        assert logger1 is logger2

    def test_audit_log_convenience(self):
        """audit_log should use global logger"""
        entry = audit_log(
            action=AuditAction.SYSTEM_STARTUP,
            details={"version": "5.23"},
        )

        assert entry.action == AuditAction.SYSTEM_STARTUP
        assert entry.details["version"] == "5.23"
