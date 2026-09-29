"""Supported source profile: MAME set hgkairak "Taisen Hot Gimmick Kairakuten (Japan)" (romset good in MAME 0.289)."""
import hashlib
import pathlib
import zipfile


class SourceError(RuntimeError):
    pass


PROFILE = {
    "1.u22": (524288, "b63d02fc15f03b93a74f5549fad236939905e382"),
    "2.u23": (524288, "1be7793b1f9a0a738519b4b4f663b247011870db"),
    "prog.u1": (1048576, "0ea5717e0b9e6c27aaf61f7e4909ed9a353b4d3b"),
    "0l.u2": (4194304, "6f6c1a75615f6a1df4d9bc97225b8e1422eb114a"),
    "0h.u11": (4194304, "1b6690ead9941171086afc89d95292c40348a15b"),
    "1l.u3": (4194304, "0ce47b1c6da1a8ec3fd341d903d6a3e0447529e2"),
    "1h.u12": (4194304, "d98c3df589f5a707043979ede44c397705c13d11"),
    "2l.u4": (4194304, "592b609f665a8a6af169611d6dbe7580df22e0c8"),
    "2h.u13": (4194304, "9001d7484ad85d1febf9c1b925445246dfd66419"),
    "3l.u5": (4194304, "cfe7651a48549a15f3fa81c744cf9204cd4f6f9a"),
    "3h.u14": (4194304, "a550b30fa854bab11389a81fb73479bec0f4a5ff"),
    "4l.u6": (4194304, "9cb2f29d123065d62a42743307db3f949432e2d5"),
    "4h.u15": (4194304, "8495a15a2b2bd5d7324264b388f3b7e5a7d36cd6"),
    "5l.u7": (4194304, "324ffcfa1b1b9def00c15f628c59cea1d09b031d"),
    "5h.u16": (4194304, "90c1695c89c059852f8b4f714b3dfee006839b44"),
    "snd0.u10": (4194304, "041e3118f7a838dcc9fb99a1028fb48a452ba1d9"),
    "snd1.u19": (4194304, "51d96cc4e9da81cbd1e815c652707407e6c7c3ae"),
}


def load(path) -> dict[str, bytes]:
    """Load every profile file from a zip or directory and verify size and SHA1."""
    path = pathlib.Path(path)
    if path.is_dir():
        read = lambda n: (path / n).read_bytes() if (path / n).is_file() else None
    elif zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        names = set(z.namelist())
        read = lambda n: z.read(n) if n in names else None
    else:
        raise SourceError(f"source not found or not a zip/directory: {path}")
    files, errors = {}, []
    for name, (size, sha1) in PROFILE.items():
        data = read(name)
        if data is None:
            errors.append(f"{name}: missing")
        elif len(data) != size or hashlib.sha1(data).hexdigest() != sha1:
            errors.append(f"{name}: size/SHA1 mismatch")
        else:
            files[name] = data
    if errors:
        raise SourceError("unsupported source: " + "; ".join(errors))
    return files
