"""Read-only SQL over the local cinema database (views only). Security core: no I/O besides the SQLite file.

Layers (each one alone forbids writes; together they also bound cost):
  validator.py   one SELECT, AST checks, view/column/function whitelists, rewritten text is what runs
  connection.py  mode=ro + immutable, query_only, trusted_schema off, SQLite limits, deny-by-default authorizer
  executor.py    deadline, row and size caps, plan check, typed errors
"""
