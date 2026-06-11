"""Creation-flywheel feature package.

Benchmark-content analysis + my-content diagnosis. Platform-agnostic by design:
domain models and repositories key off a ``platform`` string, and storage sits
behind repository interfaces so SQLite can be swapped for Supabase later.
"""
