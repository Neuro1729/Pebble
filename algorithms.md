# BusTub: Data Structures & Algorithms Inventory

Analyzed from the official [cmu-db/bustub](https://github.com/cmu-db/bustub) repository (master branch).

BusTub is an educational relational DBMS in C++ for CMU 15-445/645. It covers indexing, caching, SQL execution, concurrency, recovery scaffolding, and primer DS homework.

**Important:** The public repo is teaching starter code. Many algorithms have class definitions and tests but contain `TODO` / `UNIMPLEMENTED` methods. Below, **Starter** means student work remains; **Scaffold** means headers/helpers exist with little student logic; **Present** means usable reference or course infrastructure.

Use this list as the prerequisite map before building Pebble.

---

## 1. Data structures in BusTub

| Data structure | Purpose | Status | Source |
| --- | --- | --- | --- |
| B+ Tree | Ordered index: lookup, range scan, insert/delete, split/merge | Starter | [`b_plus_tree.cpp`](https://github.com/cmu-db/bustub/blob/master/src/storage/index/b_plus_tree.cpp) |
| Extendible Hash Table (disk) | Dynamic hashing, directory/bucket split, equality lookup | Starter | [`disk_extendible_hash_table.cpp`](https://github.com/cmu-db/bustub/blob/master/src/container/disk/hash/disk_extendible_hash_table.cpp) |
| Linear Probe Hash Table (disk) | Open-addressing on-disk hash index | Starter / legacy | [`linear_probe_hash_table.cpp`](https://github.com/cmu-db/bustub/blob/master/src/container/disk/hash/linear_probe_hash_table.cpp) |
| STL ordered / unordered indexes | Teaching wrappers over `std::map` / `std::unordered_map` as indexes | Present | [`stl_ordered.h`](https://github.com/cmu-db/bustub/blob/master/src/include/storage/index/stl_ordered.h), [`stl_unordered.h`](https://github.com/cmu-db/bustub/blob/master/src/include/storage/index/stl_unordered.h) |
| Persistent Trie | String-keyed store, structural sharing, immutable snapshots | Starter (P0) | [`trie.cpp`](https://github.com/cmu-db/bustub/blob/master/src/primer/trie.cpp) |
| Skip List | Probabilistic ordered set; concurrent via `shared_mutex` | Starter (P0) | [`skiplist.cpp`](https://github.com/cmu-db/bustub/blob/master/src/primer/skiplist.cpp) |
| Robin Hood Hash Set | Open-addressing hash set with displacement probing | Starter (P0) | [`robin_hood_hash_set.cpp`](https://github.com/cmu-db/bustub/blob/master/src/primer/robin_hood_hash_set.cpp) |
| OR-Set (CRDT) | Observed-remove set; concurrent/replica merge intuition | Starter (P0) | [`orset.cpp`](https://github.com/cmu-db/bustub/blob/master/src/primer/orset.cpp) |
| Count-Min Sketch | Approximate frequency / heavy hitters | Starter (P0) | [`count_min_sketch.h`](https://github.com/cmu-db/bustub/blob/master/src/include/primer/count_min_sketch.h) |
| HyperLogLog (+ Presto variant) | Approximate distinct count | Starter (P0) | [`hyperloglog.h`](https://github.com/cmu-db/bustub/blob/master/src/include/primer/hyperloglog.h), [`hyperloglog_presto.h`](https://github.com/cmu-db/bustub/blob/master/src/include/primer/hyperloglog_presto.h) |
| Hash Map (`unordered_map`) | Page table, txn metadata, hash-agg / hash-join build | Present (usage) | e.g. [`aggregation_executor.h`](https://github.com/cmu-db/bustub/blob/master/src/include/execution/executors/aggregation_executor.h) |
| Doubly linked lists (`std::list`) | ARC/LRU-K recency & frequency lists, ghost entries | Starter | [`arc_replacer.h`](https://github.com/cmu-db/bustub/blob/master/src/include/buffer/arc_replacer.h) |
| Queues / Deques / Channel | Disk I/O request queues, worker handoff | Partial | [`channel.h`](https://github.com/cmu-db/bustub/blob/master/src/include/common/channel.h), [`disk_scheduler.cpp`](https://github.com/cmu-db/bustub/blob/master/src/storage/disk/disk_scheduler.cpp) |
| Heaps / Priority Queues | Top-N / Top-N-per-group | Starter | [`topn_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/topn_executor.cpp), [`topn_per_group_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/topn_per_group_executor.cpp) |
| Slotted Pages | Variable-length tuples in fixed-size disk pages | Present / extend | [`table_page.h`](https://github.com/cmu-db/bustub/blob/master/src/include/storage/page/table_page.h) |
| Table Heap + RID + Tuple | Append-only heap file; record id `(page_id, slot)` | Present | [`table_heap.h`](https://github.com/cmu-db/bustub/blob/master/src/include/storage/table/table_heap.h), [`rid.h`](https://github.com/cmu-db/bustub/blob/master/src/include/common/rid.h) |
| Intermediate Result Pages | Spill pages for hash join / external sort | Starter design | [`intermediate_result_page.h`](https://github.com/cmu-db/bustub/blob/master/src/include/storage/page/intermediate_result_page.h) |
| Page + Page Guards | Frame contents; RAII shared/exclusive page latches | Starter (guards) | [`page_guard.h`](https://github.com/cmu-db/bustub/blob/master/src/include/storage/page/page_guard.h) |
| Wait-for Graph | Txn waits edges for deadlock detection | Starter | [`lock_manager.h`](https://github.com/cmu-db/bustub/blob/master/src/include/concurrency/lock_manager.h) |
| Version chains / Undo logs | Prior tuple versions for MVCC visibility | Partial + Starter | [`transaction.h`](https://github.com/cmu-db/bustub/blob/master/src/include/concurrency/transaction.h) |
| Watermark structure | Oldest active read timestamp for GC | Starter | [`watermark.h`](https://github.com/cmu-db/bustub/blob/master/src/include/concurrency/watermark.h) |
| Catalog / Schema / Column | Metadata: tables, indexes, types | Present | [`catalog.h`](https://github.com/cmu-db/bustub/blob/master/src/include/catalog/catalog.h) |
| Type / Value system | Typed SQL values, comparisons, vector type | Present | [`type/`](https://github.com/cmu-db/bustub/tree/master/src/type), [`vector_type.cpp`](https://github.com/cmu-db/bustub/blob/master/src/type/vector_type.cpp) |
| Plan / Expression trees | Logical/physical operators + scalar expressions | Present | [`execution/plans/`](https://github.com/cmu-db/bustub/tree/master/src/include/execution/plans), [`execution/expressions/`](https://github.com/cmu-db/bustub/tree/master/src/include/execution/expressions) |
| WAL Log Records | INSERT/UPDATE/DELETE/BEGIN/COMMIT/ABORT/NEWPAGE records + LSN chain | Scaffold | [`log_record.h`](https://github.com/cmu-db/bustub/blob/master/src/include/recovery/log_record.h) |

B+Tree notes: unique-key oriented; internal + leaf pages; leaf sibling links for range scan; recent leaf format includes tombstone buffer for deletes. Nodes live in buffer-pool pages, not `new[]` heaps.

---

## 2. Algorithms in BusTub

### 2.1 Buffer management and caching

| Algorithm | How it works | Status | File |
| --- | --- | --- | --- |
| Buffer Pool Manager | `page_id → frame`, pin count, dirty bit, fetch/new/delete/flush | Starter | [`buffer_pool_manager.cpp`](https://github.com/cmu-db/bustub/blob/master/src/buffer/buffer_pool_manager.cpp) |
| ARC (Adaptive Replacement Cache) | T1/T2 + ghost lists; balances recency vs frequency | Starter (default replacer in recent BPM) | [`arc_replacer.cpp`](https://github.com/cmu-db/bustub/blob/master/src/buffer/arc_replacer.cpp) |
| LRU-K | Evict by backward K-distance of accesses | Starter | [`lru_k_replacer.cpp`](https://github.com/cmu-db/bustub/blob/master/src/buffer/lru_k_replacer.cpp) |
| Clock | Circular scan + reference bits | Legacy / educational | [`clock_replacer.cpp`](https://github.com/cmu-db/bustub/blob/master/src/buffer/clock_replacer.cpp) |
| LRU | Classic recency list eviction | Legacy / educational | [`lru_replacer.cpp`](https://github.com/cmu-db/bustub/blob/master/src/buffer/lru_replacer.cpp) |
| Async disk scheduling | Producer-consumer queue, workers, mutex/CV | Partial | [`disk_scheduler.cpp`](https://github.com/cmu-db/bustub/blob/master/src/storage/disk/disk_scheduler.cpp) |
| Reader-writer page latching | Shared read / exclusive write; RAII guards | Starter | [`rwlatch.h`](https://github.com/cmu-db/bustub/blob/master/src/include/common/rwlatch.h), page guards |

### 2.2 Index algorithms

| Algorithm | Notes | Status |
| --- | --- | --- |
| B+Tree search / insert / delete | Binary search inside node; split at `max_size`; merge/redistribute | Starter |
| B+Tree range iterator | Leaf-chain walk | Starter |
| Optimistic latch crabbing | Acquire child, release parent when safe; no whole-tree latch | Starter (P2 concurrency) |
| Extendible hashing | Global/local depth, directory doubling, bucket split | Starter |
| Linear probing | Probe sequence on hash table pages | Starter / legacy |
| MurmurHash-style key hash | Used by hash indexes / utilities | Present (`third_party/murmur3`, `hash_util.h`) |

### 2.3 SQL query execution (Volcano iterators)

Each executor exposes `Init` / `Next` (pull-based). Typical complexities below are algorithmic, not BusTub benchmarks. Join/sort/agg/Top-N bodies are mostly student TODOs.

| Algorithm | How it works | Typical complexity | File |
| --- | --- | --- | --- |
| Sequential Scan | Walk table heap; optional filter | O(N) | [`seq_scan_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/seq_scan_executor.cpp) |
| Index Scan | Point/range via index | O(log N + K) | [`index_scan_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/index_scan_executor.cpp) |
| Filter / Projection | Predicate & column eval | O(N) | [`filter_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/filter_executor.cpp), [`projection_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/projection_executor.cpp) |
| Nested Loop Join | For each outer, scan inner; INNER + LEFT | O(N × M) | [`nested_loop_join_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/nested_loop_join_executor.cpp) |
| Hash Join | Build hash table, probe; may spill to temp pages | Expected O(N + M) | [`hash_join_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/hash_join_executor.cpp) |
| Index Nested Loop Join | Outer row → index probe on inner | Index-dependent | [`nested_index_join_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/nested_index_join_executor.cpp) |
| Hash Aggregation | Group-by hash table; COUNT/SUM/MIN/MAX | Expected O(N) | [`aggregation_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/aggregation_executor.cpp) |
| External Merge Sort | Sort runs on temp pages; scaffold is 2-way merge | O(N log N) | [`external_merge_sort_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/external_merge_sort_executor.cpp) |
| Sort (in-memory path) | Plan node companion | O(N log N) | [`sort_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/sort_executor.cpp) |
| Limit | Stop after K tuples | O(K) | [`limit_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/limit_executor.cpp) |
| Top-N | Bounded heap of best K | O(N log K) | [`topn_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/topn_executor.cpp) |
| Top-N Per Group | Heap per group key | O(N log K) avg | [`topn_per_group_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/topn_per_group_executor.cpp) |
| Window Aggregation | Partition / order / frame aggs | Partition-dependent | [`window_function_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/window_function_executor.cpp) |
| Insert / Update / Delete | Mutate heap (+ index maintenance in projects) | O(cost of writes) | [`insert_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/insert_executor.cpp), [`update_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/update_executor.cpp), [`delete_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/delete_executor.cpp) |
| Values / Mock Scan | Constant rows; testing scans | Present | [`values_executor.cpp`](https://github.com/cmu-db/bustub/blob/master/src/execution/values_executor.cpp) |

### 2.4 Binder, planner, optimizer

Pipeline: SQL text → **Binder** (names/types) → **Planner** (plan tree) → **Optimizer** (rule rewrites) → **ExecutionEngine**.

| Rule / pass | Idea | Status (approx.) | File |
| --- | --- | --- | --- |
| Merge filter into scan | Push predicate into seq scan | Often present | [`merge_filter_scan.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/merge_filter_scan.cpp) |
| Merge filter into NLJ | Combine filter with join | Often present | [`merge_filter_nlj.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/merge_filter_nlj.cpp) |
| Merge / eliminate projection | Remove redundant projects | Often present | [`merge_projection.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/merge_projection.cpp) |
| Eliminate true filter | Drop `WHERE true` | Present | [`eliminate_true_filter.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/eliminate_true_filter.cpp) |
| Column pruning | Project only needed columns | Partial / evolving | [`column_pruning.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/column_pruning.cpp) |
| SeqScan → IndexScan | Use index when predicate matches | Starter | [`seqscan_as_indexscan.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/seqscan_as_indexscan.cpp) |
| OrderBy → IndexScan | Avoid sort if index order matches | Starter | [`order_by_index_scan.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/order_by_index_scan.cpp) |
| NLJ → Hash Join | Equality join rewrite | Starter | [`nlj_as_hash_join.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/nlj_as_hash_join.cpp) |
| NLJ → Index Join | Rewrite when inner has usable index | Starter / present | [`nlj_as_index_join.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/nlj_as_index_join.cpp) |
| Sort + Limit → Top-N | Avoid full materializing sort | Starter | [`sort_limit_as_topn.cpp`](https://github.com/cmu-db/bustub/blob/master/src/optimizer/sort_limit_as_topn.cpp) |

BusTub optimization is **rule-based**, not a full Cascades/System R cost-based search.

### 2.5 Concurrency and transactions

| Algorithm / technique | Purpose | Status |
| --- | --- | --- |
| MVCC (optimistic / HyPer-style in recent P4) | Snapshot reads via version chains | Starter |
| Undo-log version chains | Reconstruct older tuple versions | Partial helpers + Starter |
| Timestamp watermarks | Track oldest active snapshot for GC | Starter |
| Lock manager + multi-granularity locking | Row/table locks; 2PL-style coordination | Starter (varies by semester) |
| Wait-for graph cycle detection | Deadlock detection | Starter |
| Commit / Abort / isolation checks | Transaction lifecycle | Starter |

### 2.6 Logging and recovery (scaffold; often lecture-only for projects)

| Piece | Purpose | Status |
| --- | --- | --- |
| WAL log records + LSN / prevLSN | Write-ahead of heap changes | Scaffold |
| Log Manager | Append/flush log | Scaffold |
| Checkpoint Manager | Truncate recovery window | Scaffold |
| Log Recovery | Redo/undo style restart | Scaffold headers |

Record types in [`log_record.h`](https://github.com/cmu-db/bustub/blob/master/src/include/recovery/log_record.h): `INSERT`, `MARKDELETE`, `APPLYDELETE`, `ROLLBACKDELETE`, `UPDATE`, `BEGIN`, `COMMIT`, `ABORT`, `NEWPAGE`.

Know **ARIES** (Analysis → Redo → Undo) from lectures even if you do not fully implement it for Pebble v1.

---

## 3. What was missing from the first pass (now included)

These exist in the BusTub tree but were easy to miss:

1. **Clock** and classic **LRU** replacers (alongside ARC / LRU-K)
2. **Linear probe** disk hash table
3. **Skip list**, **Robin Hood hash set**, **OR-Set**, **HyperLogLog Presto**
4. **STL ordered/unordered** indexes
5. **Table heap, RID, tuple, intermediate spill pages, page guards**
6. **Top-N per group**, full **optimizer rule file set**, **binder/planner** pipeline
7. **Recovery** headers (`log_record`, `log_manager`, `checkpoint_manager`, `log_recovery`)
8. **Watermark** GC helper
9. **Type/Value** system including **vector** type

---

## 4. What to learn before building Pebble

Study order aligned with BusTub’s real dependency chain:

1. **Pages, RID, table heap, buffer pool** (pin/dirty/replacement + latches)
2. **B+ Tree** (layout, binary search, split/merge, then latch crabbing)
3. **Hash tables** (in-memory for join/agg; extendible or linear probe as index)
4. **ARC or LRU-K** (lists + hash maps + eviction policy)
5. **Volcano executors**: SeqScan → Filter → NLJ → Hash Join/Agg → External Sort → Top-N
6. **Rule-based optimizer** (a few rewrites beat a tiny cost model)
7. **MVCC or locking** + wait-for deadlock detection
8. **WAL + simple recovery** (even a reduced ARIES)
9. Primers as stretch: **Trie, Skip List, sketches, Robin Hood, OR-Set**

### Five deepest topics (highest leverage)

1. B+ Trees (pages + latches)
2. Extendible hashing
3. ARC / LRU-K
4. Hash join + hash aggregation
5. MVCC (or strict 2PL, if you pick locking instead)

---

## 5. Biggest takeaway

BusTub shows how textbook DS become **database machinery**:

- A B+Tree node is a **disk page** under a **buffer frame** with **latches**, not a heap object.
- A hash table is an **on-disk index**, a **join build side**, or an **aggregation table**.
- A linked list + map is a **cache replacer**.
- A graph is a **deadlock detector**.
- A version chain is **isolation**.

Starter `TODO`s are intentional: the repo teaches by forcing you to finish the algorithms. For Pebble, implement the same ideas with a smaller surface, but do not skip the storage → index → executor → txn order.

---

## Source

- Repository: [https://github.com/cmu-db/bustub](https://github.com/cmu-db/bustub)
- Course: [https://15445.courses.cs.cmu.edu](https://15445.courses.cs.cmu.edu)
