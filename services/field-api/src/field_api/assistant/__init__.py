"""Field Assistant (M3 contract §4): the spoken router between the operator, the open work and the job engine.

It talks and routes; it never posts and never sees book or expected quantities on count tasks. The phone
executes the returned actions through its own job runner; posting still needs the operator's own confirm.
"""
