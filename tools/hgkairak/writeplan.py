"""Expected Write plan: every output change is registered, verified against immutable source,
checked for overlap/protected ranges, applied all-or-nothing, and audited against the final diff."""
from dataclasses import dataclass


class PlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Write:
    writer: str
    file: str
    offset: int
    expected: bytes
    final: bytes


class WritePlan:
    def __init__(self, source: dict[str, bytes], protected: dict[str, list[tuple[int, int]]] | None = None):
        self.source = source
        self.protected = protected or {}
        self.writes: list[Write] = []

    def add(self, writer: str, file: str, offset: int, expected: bytes, final: bytes) -> None:
        if file not in self.source:
            raise PlanError(f"{writer}: unknown file {file}")
        if len(expected) != len(final):
            raise PlanError(f"{writer}: expected/final length mismatch")
        if offset < 0 or offset + len(final) > len(self.source[file]):
            raise PlanError(f"{writer}: range {offset:#x}+{len(final)} outside {file}")
        self.writes.append(Write(writer, file, offset, bytes(expected), bytes(final)))

    def verify(self) -> None:
        owner: dict[tuple[str, int], str] = {}
        for w in self.writes:
            src = self.source[w.file][w.offset:w.offset + len(w.expected)]
            if src != w.expected:
                raise PlanError(f"{w.writer}: expected source mismatch in {w.file} at {w.offset:#x}")
            for lo, hi in self.protected.get(w.file, []):
                if w.offset < hi and lo < w.offset + len(w.final):
                    raise PlanError(f"{w.writer}: protected range {w.file} {lo:#x}-{hi:#x}")
            for i in range(len(w.final)):
                key = (w.file, w.offset + i)
                if key in owner:
                    raise PlanError(f"{w.writer}: overlap with {owner[key]} in {w.file} at {key[1]:#x}")
                owner[key] = w.writer

    def apply(self) -> dict[str, bytearray]:
        self.verify()
        out = {f: bytearray(d) for f, d in self.source.items()}
        for w in self.writes:
            out[w.file][w.offset:w.offset + len(w.final)] = w.final
        self.audit(out)
        return out

    def audit(self, out: dict[str, bytearray]) -> None:
        covered: dict[str, set[int]] = {}
        for w in self.writes:
            covered.setdefault(w.file, set()).update(range(w.offset, w.offset + len(w.final)))
        for f, src in self.source.items():
            dst = out[f]
            if len(dst) != len(src):
                raise PlanError(f"unexplained size change in {f}")
            cov = covered.get(f, set())
            for i, (a, b) in enumerate(zip(src, dst)):
                if a != b and i not in cov:
                    raise PlanError(f"unexplained change in {f} at {i:#x}")
