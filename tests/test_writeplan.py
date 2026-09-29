"""Expected Write plan: verification against immutable source and final-diff audit."""
import pytest

from hgkairak.writeplan import PlanError, WritePlan


SRC = {"a.bin": bytes(16), "b.bin": bytes(range(16))}


def test_apply_produces_expected_output_and_leaves_source_untouched():
    p = WritePlan(SRC)
    p.add("t1", "a.bin", 2, bytes(2), b"\x11\x22")
    out = p.apply()
    assert out["a.bin"][2:4] == b"\x11\x22"
    assert SRC["a.bin"] == bytes(16)
    assert out["b.bin"] == SRC["b.bin"]


def test_expected_source_mismatch_fails():
    p = WritePlan(SRC)
    p.add("t1", "b.bin", 0, b"\xff", b"\x00")
    with pytest.raises(PlanError, match="expected source"):
        p.apply()


def test_overlapping_writers_fail():
    p = WritePlan(SRC)
    p.add("t1", "a.bin", 0, bytes(4), b"1234")
    p.add("t2", "a.bin", 3, bytes(2), b"56")
    with pytest.raises(PlanError, match="overlap"):
        p.apply()


def test_out_of_range_and_length_mismatch_fail():
    p = WritePlan(SRC)
    with pytest.raises(PlanError):
        p.add("t1", "a.bin", 15, bytes(2), b"12")
    with pytest.raises(PlanError):
        p.add("t2", "a.bin", 0, bytes(2), b"123")
    with pytest.raises(PlanError):
        p.add("t3", "zzz.bin", 0, b"", b"")


def test_protected_range_write_fails():
    p = WritePlan(SRC, protected={"a.bin": [(8, 12)]})
    p.add("t1", "a.bin", 10, bytes(1), b"\x01")
    with pytest.raises(PlanError, match="protected"):
        p.apply()


def test_audit_detects_unregistered_change():
    p = WritePlan(SRC)
    p.add("t1", "a.bin", 0, bytes(1), b"\x01")
    out = p.apply()
    out["a.bin"][5] = 0x99
    with pytest.raises(PlanError, match="unexplained"):
        p.audit(out)


def test_failed_plan_produces_nothing():
    p = WritePlan(SRC)
    p.add("ok", "a.bin", 0, bytes(1), b"\x01")
    p.add("bad", "b.bin", 0, b"\x07", b"\x00")
    with pytest.raises(PlanError):
        p.apply()
