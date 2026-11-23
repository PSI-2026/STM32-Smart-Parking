"""A candidate never replaces the accepted boot/sequence high-water mark alone."""


def resume_candidate(candidate, *, boot, sequence, age, now, runtime, payload, threshold):
    if candidate and candidate["boot"] == boot and sequence == candidate["sequence"]:
        # Preserve this identity even across interruption/restart. A distinct
        # sample must establish the next baseline when continuity is lost.
        return candidate, False
    if candidate and candidate["boot"] == boot and candidate["runtime"] == runtime:
        elapsed = now - candidate["at"]
        estimated = candidate["age"] + max(0, elapsed)
        if not candidate.get("interrupted", False) and 0 <= elapsed and estimated < threshold:
            if 0 < sequence - candidate["sequence"] < 0x80000000 and age < threshold:
                return None, True
    return dict(boot=boot, sequence=sequence, age=age, at=now, runtime=runtime, payload=payload), False
