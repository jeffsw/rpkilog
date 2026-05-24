"""
Tests for vrp_diff_list() and its wrapper (for e2e tests) vrp_diff_from_files()

TODO: Implement synthetic tests using ROAs with ASNs 64496 to 64499 and prefixes 192.0.2.0/24,
  198.51.100.0/24, 203.0.113.0/24 invoking vrp_diff_list() directly:
  - [ ] Two identical lists → returns empty list (all UNCHANGED, nothing emitted)
  - [ ] ROA present only in old_roas → emits DELETE
  - [ ] ROA present only in new_roas → emits NEW
  - [ ] ROA with same primary key but different expires in old vs. new → emits REPLACE
  - [ ] One ROA in old, one ROA in new, different primary keys → emits one DELETE and one NEW
  - [ ] Mixed batch: some UNCHANGED, one DELETE, one NEW, one REPLACE → all four verbs in one call

TODO: Implement the following tests using the golden test_data files below and vrp_diff_from_files()
  golden test data files:
    * old snapshot file rpkiclient_summary_20250720T093135Z.json.bz2
    * new snapshot file rpkiclient_summary_20250720T100145Z.json.bz2
    * verified correct diff file rpkiclient_vrpdiff_20250720T100145Z.json.bz2
  tests to implement:
    - [ ] compare the test resulting diff metadata to the golden result metadata in
      rpkiclient_vrpdiff_20250720T100145Z verifying the diff_count is equal.
    - [ ] count the number of verb: DELETE, NEW, and REPLACE records in the test diff and ensure they
      add up to the diff_count.
"""
