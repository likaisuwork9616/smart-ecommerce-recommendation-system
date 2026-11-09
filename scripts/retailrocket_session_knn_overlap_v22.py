"""Symmetric connection adapters for the sealed overlap-only comparison."""
from types import SimpleNamespace
from scripts import retailrocket_session_knn_sql_v4 as native
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone, OVERLAP_SQL
from scripts.retailrocket_session_knn_overlap_candidate_v21 import CANDIDATE_SQL


class StatementConnection:
    def __init__(self, connection, statement):
        self.connection, self.statement = connection, statement

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args, **kwargs):
        return self.connection.execute(self.statement if sql == OVERLAP_SQL else sql, *args, **kwargs)


def make_verifier(mode):
    if mode not in ('baseline', 'group_before_size_join'):
        raise ValueError('Only the original SQL and sealed V21 candidate are allowed')
    statement = OVERLAP_SQL if mode == 'baseline' else CANDIDATE_SQL
    def predict(connection, *args, **kwargs):
        return native.predict(StatementConnection(connection, statement), *args, **kwargs)
    return _clone(pair.verify_selected, sql=SimpleNamespace(predict=predict, prepare_catalog=native.prepare_catalog))
