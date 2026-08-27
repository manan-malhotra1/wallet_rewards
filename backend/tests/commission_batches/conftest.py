"""Commission-batch suite fixtures.

`batch_fixture` and `maker_admin` are registered in the ROOT conftest (three
suites need them), and `BatchFixture` lives in `tests/fixtures/commission.py`.
This file stays so the directory keeps its own conftest hook point.
"""

from __future__ import annotations

from tests.fixtures.commission import BatchFixture  # noqa: F401
