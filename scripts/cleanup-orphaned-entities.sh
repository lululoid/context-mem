#!/bin/bash

set -euo pipefail

DB_PATH=".context-mem/store.db"

while getopts "d:" opt; do
  case $opt in
    d) DB_PATH="$OPTARG" ;;
    *) echo "Usage: $0 [-d <database>]" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$DB_PATH" ]]; then
  echo "Error: database not found: $DB_PATH" >&2
  exit 1
fi

ORPHAN_WHERE="
  knowledge_id IS NULL
  AND LENGTH(name) BETWEEN 20 AND 30
  AND name GLOB '[0-9A-Z]*'
  AND metadata = '{}'
"

# Count orphaned ULID entities (regardless of relationships)
ORPHAN_COUNT=$(sqlite3 "$DB_PATH" "
  SELECT COUNT(*) FROM entities WHERE $ORPHAN_WHERE;
")

# Count orphaned entities that have NO relationships (truly orphaned, safe to delete)
SAFE_COUNT=$(sqlite3 "$DB_PATH" "
  SELECT COUNT(*) FROM entities
  WHERE $ORPHAN_WHERE
    AND id NOT IN (SELECT from_entity FROM relationships)
    AND id NOT IN (SELECT to_entity FROM relationships);
")

# Count orphaned entities that HAVE relationships (need manual review)
REVIEW_COUNT=$((ORPHAN_COUNT - SAFE_COUNT))

REL_COUNT=$(sqlite3 "$DB_PATH" "
  SELECT COUNT(*) FROM relationships
  WHERE from_entity IN (SELECT id FROM entities WHERE $ORPHAN_WHERE)
     OR to_entity IN (SELECT id FROM entities WHERE $ORPHAN_WHERE);
")

if [[ "$ORPHAN_COUNT" -eq 0 ]]; then
  echo "No orphaned ULID entities found in $DB_PATH"
  exit 0
fi

echo "Found $ORPHAN_COUNT orphaned ULID entity(ies) in $DB_PATH"
echo "  Safe to delete (no relationships): $SAFE_COUNT"
echo "  Need manual review (has $REL_COUNT relationship(s)): $REVIEW_COUNT"

if [[ "$SAFE_COUNT" -gt 0 ]]; then
  echo ""
  echo "Deleting $SAFE_COUNT truly orphaned entity(ies)..."
  sqlite3 "$DB_PATH" "
    DELETE FROM entities
    WHERE $ORPHAN_WHERE
      AND id NOT IN (SELECT from_entity FROM relationships)
      AND id NOT IN (SELECT to_entity FROM relationships);
  "
  echo "Deleted $SAFE_COUNT orphaned entity(ies)"
fi

if [[ "$REVIEW_COUNT" -gt 0 ]]; then
  echo ""
  echo "WARNING: $REVIEW_COUNT orphaned entity(ies) have relationship(s) and were NOT deleted."
  echo "Review them manually before removing:"
  sqlite3 "$DB_PATH" "
    SELECT e.id, e.name, e.entity_type,
           GROUP_CONCAT(DISTINCT r.relationship_type) as relationships
    FROM entities e
    LEFT JOIN relationships r ON r.from_entity = e.id OR r.to_entity = e.id
    WHERE $ORPHAN_WHERE
      AND (e.id IN (SELECT from_entity FROM relationships) OR e.id IN (SELECT to_entity FROM relationships))
    GROUP BY e.id, e.name, e.entity_type;
  "
fi
