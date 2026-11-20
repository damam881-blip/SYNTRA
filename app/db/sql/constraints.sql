-- ============================================================================
-- SYNTRA TASK-06 database constraints, integrity triggers and read views
-- Applied after SQLAlchemy/Alembic creates the tables.
-- PostgreSQL 13+.
-- ============================================================================

-- SHA-256 verification uses the PostgreSQL 11+ core hash functions
-- (sha256(bytea)); no optional extension such as pgcrypto is required.

-- ---------------------------------------------------------------------------
-- Immutability guard.  Normal application writes cannot UPDATE/DELETE
-- historical rows.  The project deletion / retention service sets
-- ``SET LOCAL syntra.purge_mode = 'on'`` inside its transaction.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_guard_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('syntra.purge_mode', true), 'off') = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'immutable table % cannot be modified by normal writes',
        TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_project_revision_immutable ON project_revision;
CREATE TRIGGER trg_project_revision_immutable
    BEFORE UPDATE OR DELETE ON project_revision
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_snapshot_ref_immutable ON snapshot_ref;
CREATE TRIGGER trg_snapshot_ref_immutable
    BEFORE UPDATE OR DELETE ON snapshot_ref
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_ping_command_immutable ON ping_test_command;
CREATE TRIGGER trg_ping_command_immutable
    BEFORE UPDATE OR DELETE ON ping_test_command
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_ping_result_immutable ON ping_test_result;
CREATE TRIGGER trg_ping_result_immutable
    BEFORE UPDATE OR DELETE ON ping_test_result
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_error_envelope_immutable ON error_envelope;
CREATE TRIGGER trg_error_envelope_immutable
    BEFORE UPDATE OR DELETE ON error_envelope
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_action_log_no_update ON action_log;
CREATE TRIGGER trg_action_log_no_update
    BEFORE UPDATE ON action_log
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_ping_log_no_update ON ping_log;
CREATE TRIGGER trg_ping_log_no_update
    BEFORE UPDATE ON ping_log
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

DROP TRIGGER IF EXISTS trg_error_log_no_update ON error_log;
CREATE TRIGGER trg_error_log_no_update
    BEFORE UPDATE ON error_log
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

-- Checkpoints are append-only markers; retention may delete them.
DROP TRIGGER IF EXISTS trg_checkpoint_no_update ON checkpoint;
CREATE TRIGGER trg_checkpoint_no_update
    BEFORE UPDATE ON checkpoint
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

-- ---------------------------------------------------------------------------
-- TASK-04: one active connection per interface across BOTH endpoint fields.
-- Every topology mutation locks the project row first, so this check is
-- race-safe under the documented transaction policy.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_connection_occupancy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM connection c
        WHERE c.project_id = NEW.project_id
          AND c.connection_id <> NEW.connection_id
          AND (
              c.interface_a_id IN (NEW.interface_a_id, NEW.interface_b_id)
              OR c.interface_b_id IN (NEW.interface_a_id, NEW.interface_b_id)
          )
    ) THEN
        RAISE EXCEPTION
            'interface is already occupied by another connection in project %',
            NEW.project_id
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_connection_occupancy ON connection;
CREATE TRIGGER trg_connection_occupancy
    BEFORE INSERT OR UPDATE OF interface_a_id, interface_b_id ON connection
    FOR EACH ROW EXECUTE FUNCTION syntra_check_connection_occupancy();

-- ---------------------------------------------------------------------------
-- TASK-04: StaticRoute is owned by a ROUTER only.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_static_route_router()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    device_kind_value text;
BEGIN
    SELECT kind::text INTO device_kind_value
    FROM device
    WHERE project_id = NEW.project_id AND device_id = NEW.router_device_id;

    IF device_kind_value IS NULL THEN
        RAISE EXCEPTION 'router device % does not belong to project %',
            NEW.router_device_id, NEW.project_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF device_kind_value <> 'ROUTER' THEN
        RAISE EXCEPTION 'static routes may only belong to ROUTER devices'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_static_route_router ON static_route;
CREATE TRIGGER trg_static_route_router
    BEFORE INSERT OR UPDATE ON static_route
    FOR EACH ROW EXECUTE FUNCTION syntra_check_static_route_router();

-- ---------------------------------------------------------------------------
-- TASK-04: V1 exposes no switch management IP.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_switch_ipv4()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    device_kind_value text;
BEGIN
    SELECT kind::text INTO device_kind_value
    FROM device
    WHERE project_id = NEW.project_id AND device_id = NEW.device_id;

    IF device_kind_value = 'L2_SWITCH' AND NEW.ipv4_address IS NOT NULL THEN
        RAISE EXCEPTION 'L2_SWITCH interfaces cannot have an IPv4 configuration'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_interface_switch_ipv4 ON interface;
CREATE TRIGGER trg_interface_switch_ipv4
    BEFORE INSERT OR UPDATE OF ipv4_address ON interface
    FOR EACH ROW EXECUTE FUNCTION syntra_check_switch_ipv4();

-- ---------------------------------------------------------------------------
-- TASK-04: default gateways are host-only (PC / SERVER).  Routers use static
-- routes instead; a stored router gateway would be silently inactive.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_host_gateway()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.default_gateway_ipv4 IS NOT NULL
       AND NEW.kind::text NOT IN ('PC', 'SERVER') THEN
        RAISE EXCEPTION
            'default_gateway_ipv4 is only permitted on PC and SERVER devices'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_device_host_gateway ON device;
CREATE TRIGGER trg_device_host_gateway
    BEFORE INSERT OR UPDATE OF default_gateway_ipv4 ON device
    FOR EACH ROW EXECUTE FUNCTION syntra_check_host_gateway();

-- ---------------------------------------------------------------------------
-- TASK-04: revision gaplessness.  The service increments project.state_revision
-- in the same transaction before inserting the audit row.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_revision_gapless()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    previous_revision bigint;
BEGIN
    SELECT MAX(revision) INTO previous_revision
    FROM project_revision
    WHERE project_id = NEW.project_id;

    IF NEW.revision <> COALESCE(previous_revision, 0) + 1 THEN
        RAISE EXCEPTION
            'revision % creates a gap for project % (previous committed revision %)',
            NEW.revision, NEW.project_id, COALESCE(previous_revision, 0)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_project_revision_gapless ON project_revision;
CREATE TRIGGER trg_project_revision_gapless
    BEFORE INSERT ON project_revision
    FOR EACH ROW EXECUTE FUNCTION syntra_check_revision_gapless();

-- ---------------------------------------------------------------------------
-- TASK-04: snapshot capture must pin the current committed revisions.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_snapshot_revisions()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    current_state_revision bigint;
    current_simulation_revision bigint;
BEGIN
    SELECT state_revision, simulation_revision
    INTO current_state_revision, current_simulation_revision
    FROM project
    WHERE project_id = NEW.project_id
    FOR UPDATE;

    IF current_state_revision IS NULL THEN
        RAISE EXCEPTION 'project % does not exist', NEW.project_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.base_state_revision <> current_state_revision
       OR NEW.base_simulation_revision <> current_simulation_revision THEN
        RAISE EXCEPTION
            'snapshot revisions (%, %) do not match project current revisions (%, %)',
            NEW.base_state_revision, NEW.base_simulation_revision,
            current_state_revision, current_simulation_revision
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_snapshot_revision_consistency ON snapshot_ref;
CREATE TRIGGER trg_snapshot_revision_consistency
    BEFORE INSERT ON snapshot_ref
    FOR EACH ROW EXECUTE FUNCTION syntra_check_snapshot_revisions();

-- ---------------------------------------------------------------------------
-- Snapshot immutability: the stored digest must equal SHA-256 of the exact
-- canonical bytes used to build the configuration projection.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_verify_snapshot_digest()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.configuration_digest <>
       encode(sha256(convert_to(NEW.canonical_json, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'snapshot digest does not match canonical configuration JSON'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_snapshot_digest ON snapshot_ref;
CREATE TRIGGER trg_snapshot_digest
    BEFORE INSERT ON snapshot_ref
    FOR EACH ROW EXECUTE FUNCTION syntra_verify_snapshot_digest();

-- ---------------------------------------------------------------------------
-- TASK-05: Ping endpoints must be PC or SERVER in the command project.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_ping_endpoints()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    source_kind text;
    destination_kind text;
BEGIN
    SELECT kind::text INTO source_kind
    FROM device
    WHERE project_id = NEW.project_id AND device_id = NEW.source_device_id;

    SELECT kind::text INTO destination_kind
    FROM device
    WHERE project_id = NEW.project_id AND device_id = NEW.destination_device_id;

    IF source_kind IS NULL THEN
        RAISE EXCEPTION 'source device % is not in project %',
            NEW.source_device_id, NEW.project_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF destination_kind IS NULL THEN
        RAISE EXCEPTION 'destination device % is not in project %',
            NEW.destination_device_id, NEW.project_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF source_kind NOT IN ('PC', 'SERVER') THEN
        RAISE EXCEPTION 'Ping source must be PC or SERVER (got %)', source_kind
            USING ERRCODE = 'check_violation';
    END IF;
    IF destination_kind NOT IN ('PC', 'SERVER') THEN
        RAISE EXCEPTION 'Ping destination must be PC or SERVER (got %)',
            destination_kind
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ping_command_endpoints ON ping_test_command;
CREATE TRIGGER trg_ping_command_endpoints
    BEFORE INSERT ON ping_test_command
    FOR EACH ROW EXECUTE FUNCTION syntra_check_ping_endpoints();

-- ---------------------------------------------------------------------------
-- TASK-05: result identity must match its accepted command exactly.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_result_command()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    command_project uuid;
    command_source uuid;
    command_destination uuid;
    command_snapshot uuid;
BEGIN
    SELECT project_id, source_device_id, destination_device_id, snapshot_id
    INTO command_project, command_source, command_destination, command_snapshot
    FROM ping_test_command
    WHERE test_id = NEW.test_id;

    IF command_project IS NULL THEN
        RAISE EXCEPTION 'Ping command % does not exist', NEW.test_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.project_id <> command_project
       OR NEW.source_device_id <> command_source
       OR NEW.destination_device_id <> command_destination
       OR NEW.snapshot_id <> command_snapshot THEN
        RAISE EXCEPTION
            'Ping result identity/snapshot does not match accepted command'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ping_result_command ON ping_test_result;
CREATE TRIGGER trg_ping_result_command
    BEFORE INSERT ON ping_test_result
    FOR EACH ROW EXECUTE FUNCTION syntra_check_result_command();

-- ---------------------------------------------------------------------------
-- Canonical JSON integrity: stored hash must equal SHA-256(canonical_json).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_verify_result_hash()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.result_sha256 <>
       encode(sha256(convert_to(NEW.canonical_json, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'Ping result SHA-256 does not match canonical JSON'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ping_result_hash ON ping_test_result;
CREATE TRIGGER trg_ping_result_hash
    BEFORE INSERT ON ping_test_result
    FOR EACH ROW EXECUTE FUNCTION syntra_verify_result_hash();

CREATE OR REPLACE FUNCTION syntra_verify_error_hash()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.canonical_sha256 <>
       encode(sha256(convert_to(NEW.canonical_json, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'Error envelope SHA-256 does not match canonical JSON'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_error_envelope_hash ON error_envelope;
CREATE TRIGGER trg_error_envelope_hash
    BEFORE INSERT ON error_envelope
    FOR EACH ROW EXECUTE FUNCTION syntra_verify_error_hash();

-- ---------------------------------------------------------------------------
-- Error snapshot must belong to the error project when both are present.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_error_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.project_id IS NOT NULL AND NEW.snapshot_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM snapshot_ref
            WHERE project_id = NEW.project_id AND snapshot_id = NEW.snapshot_id
        ) THEN
            RAISE EXCEPTION 'error snapshot does not belong to the error project'
                USING ERRCODE = 'foreign_key_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_error_snapshot_project ON error_envelope;
CREATE TRIGGER trg_error_snapshot_project
    BEFORE INSERT ON error_envelope
    FOR EACH ROW EXECUTE FUNCTION syntra_check_error_snapshot();

-- ---------------------------------------------------------------------------
-- Error log rows must agree with the immutable error envelope they reference.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_check_error_log_project()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    envelope_project uuid;
    envelope_class text;
    envelope_code text;
    envelope_message text;
BEGIN
    SELECT project_id, error_class::text, code::text, message_key
    INTO envelope_project, envelope_class, envelope_code, envelope_message
    FROM error_envelope
    WHERE error_id = NEW.error_id;

    IF envelope_class IS NULL THEN
        RAISE EXCEPTION 'error envelope % does not exist', NEW.error_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.project_id IS DISTINCT FROM envelope_project
       OR NEW.error_class::text <> envelope_class
       OR NEW.code::text <> envelope_code
       OR NEW.message_key <> envelope_message THEN
        RAISE EXCEPTION
            'error log row does not match the error envelope it references'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_error_log_consistency ON error_log;
CREATE TRIGGER trg_error_log_consistency
    BEFORE INSERT ON error_log
    FOR EACH ROW EXECUTE FUNCTION syntra_check_error_log_project();

-- ---------------------------------------------------------------------------
-- Deletion audit survives the project purge and is never rewritten.
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_tombstone_no_update ON project_tombstone;
CREATE TRIGGER trg_tombstone_no_update
    BEFORE UPDATE OR DELETE ON project_tombstone
    FOR EACH ROW EXECUTE FUNCTION syntra_guard_immutable();

-- ---------------------------------------------------------------------------
-- updated_at maintenance.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION syntra_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_project_touch_updated_at ON project;
CREATE TRIGGER trg_project_touch_updated_at
    BEFORE UPDATE ON project
    FOR EACH ROW EXECUTE FUNCTION syntra_touch_updated_at();

DROP TRIGGER IF EXISTS trg_retention_policy_touch_updated_at ON retention_policy;
CREATE TRIGGER trg_retention_policy_touch_updated_at
    BEFORE UPDATE ON retention_policy
    FOR EACH ROW EXECUTE FUNCTION syntra_touch_updated_at();

-- ---------------------------------------------------------------------------
-- Default retention policy (idempotent).
-- ---------------------------------------------------------------------------
INSERT INTO retention_policy (
    policy_name,
    action_log_retention_days,
    ping_log_retention_days,
    error_log_retention_days,
    ping_result_retention_days,
    snapshot_retention_days
)
VALUES ('default', 90, 365, 365, 365, 365)
ON CONFLICT (policy_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Read views for AI / simulation consumers.  They expose the contract arrays
-- without duplicating storage.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_ping_event AS
SELECT
    r.project_id,
    r.test_id,
    r.snapshot_id,
    e.value AS event
FROM ping_test_result r
CROSS JOIN LATERAL jsonb_array_elements(r.events_json) AS e;

CREATE OR REPLACE VIEW v_ping_diagnostic AS
SELECT
    r.project_id,
    r.test_id,
    r.snapshot_id,
    d.value AS diagnostic
FROM ping_test_result r
CROSS JOIN LATERAL jsonb_array_elements(r.diagnostics_json) AS d;

CREATE OR REPLACE VIEW v_ping_hop AS
SELECT
    r.project_id,
    r.test_id,
    r.snapshot_id,
    h.value AS hop
FROM ping_test_result r
CROSS JOIN LATERAL jsonb_array_elements(r.hop_evidence_json) AS h;

CREATE OR REPLACE VIEW v_ping_warning AS
SELECT
    r.project_id,
    r.test_id,
    r.snapshot_id,
    w.value AS warning
FROM ping_test_result r
CROSS JOIN LATERAL jsonb_array_elements(r.derived_warning_evidence_json) AS w;
