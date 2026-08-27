from __future__ import annotations
import persistent_runner as pr

_ORIGINAL_MAKE_RUNNER=pr.make_runner


def make_runner_v3():
    src=_ORIGINAL_MAKE_RUNNER()
    needle='from __future__ import annotations\n'
    patch=needle+'import v3_engine\nv3_engine.install()\n'
    if needle not in src:
        raise RuntimeError('Runner bootstrap marker missing')
    return src.replace(needle,patch,1)


def main():
    original=pr.make_runner
    pr.make_runner=make_runner_v3
    try:
        return pr.main()
    finally:
        pr.make_runner=original


if __name__=='__main__':
    raise SystemExit(main())
