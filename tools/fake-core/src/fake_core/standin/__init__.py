"""Stand-in core: a dev double of the SCMTIPS core's /v1 contract for the Field M4 slice (M4 contract section 3).

It is NOT the SCMTIPS core and must never be presented as it. It serves the paths and shapes of the core's
handover files (01, 01a, 01b) and of the ported ARO wearable client, so Field can be built and tested while the
real core is not deployed; pointing Field at the real core is settings only (FIELD_CORE_*). State is in process
memory and lost on restart, like the core's local signing key.
"""
