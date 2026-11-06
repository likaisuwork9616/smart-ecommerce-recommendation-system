"""Unadopted candidate: aggregate postings before the unique session-size join.

Only the exact overlap statement changes; original V4 prediction, tie ordering,
validation and vote accumulation execute unchanged. No performance claim.
"""
from scripts import retailrocket_session_knn_sql_v4 as original
from scripts.retailrocket_session_knn_diagnostics_v20 import OVERLAP_SQL

CANDIDATE_SQL = (
    'SELECT hits.v,hits.s,hits.n,sizes.n FROM ('
    'SELECT membership.v,membership.s,COUNT(*) AS n '
    'FROM temp.k1_v4_history AS query '
    'CROSS JOIN main.m AS membership INDEXED BY k1_v2_posting '
    'ON membership.i=query.i '
    'GROUP BY membership.v,membership.s) AS hits '
    'LEFT JOIN main.k1_v2_sizes AS sizes '
    'ON sizes.v=hits.v AND sizes.s=hits.s')


class _Connection:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, statement, *args, **kwargs):
        return self.connection.execute(CANDIDATE_SQL if statement == OVERLAP_SQL else statement,
                                       *args, **kwargs)


def predict(connection, *args, **kwargs):
    return original.predict(_Connection(connection), *args, **kwargs)
