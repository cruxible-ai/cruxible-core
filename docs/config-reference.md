# Config Reference

Cruxible Core configs are YAML files that define a decision domain: entity types, relationships, named queries, constraints, and ingestion mappings. AI agents generate these configs; Core validates and executes against them.

## Top-Level Structure

```yaml
version: "1.0"
name: "my_domain"
description: "Optional description of this decision domain"

entity_types: { ... }
relationships: [ ... ]
named_queries: { ... }
constraints: [ ... ]
ingestion: { ... }
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `version` | string | no | `"1.0"` | Config schema version |
| `name` | string | **yes** | — | Unique name for this domain |
| `description` | string | no | `null` | Human-readable description |
| `cruxible_version` | string | no | `null` | Version of cruxible-core that produced this config (auto-stamped on save) |
| `entity_types` | dict | **yes** | — | Entity type definitions |
| `relationships` | list | **yes** | — | Relationship definitions |
| `named_queries` | dict | no | `{}` | Declarative query definitions |
| `constraints` | list | no | `[]` | Validation rules |
| `ingestion` | dict | no | `{}` | Data ingestion mappings |

---

## entity_types

A dict keyed by type name. Each value defines the entity's properties.

```yaml
entity_types:
  Vehicle:
    description: "A specific vehicle (year + make + model + trim)"
    properties:
      vehicle_id:
        type: string
        primary_key: true
      year:
        type: int
        indexed: true
      make:
        type: string
        indexed: true
      model:
        type: string
        indexed: true
      trim:
        type: string
        optional: true
      engine:
        type: string
        optional: true
```

### EntityTypeSchema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `description` | string | no | `null` | Human-readable description of this entity type |
| `properties` | dict | **yes** | — | Property definitions (see below) |
| `constraints` | list[string] | no | `[]` | Constraint names that apply to this entity type |

### PropertySchema

Each property within an entity type (or relationship) is defined with:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | **yes** | — | Data type: `string`, `int`, `float`, `bool`, `date` |
| `primary_key` | bool | no | `false` | Mark as the entity's unique identifier |
| `indexed` | bool | no | `false` | Enable fast lookups on this property |
| `optional` | bool | no | `false` | Allow null/missing values |
| `default` | any | no | `null` | Default value when not provided |
| `enum` | list[string] | no | `null` | Restrict to allowed values |
| `description` | string | no | `null` | Human-readable description |

**Rules:**
- Exactly one property per entity type should have `primary_key: true`.
- `primary_key` goes on the property, not the entity type.
- Properties are required by default; set `optional: true` to allow nulls.

---

## relationships

A list of relationship definitions connecting entity types.

```yaml
relationships:
  - name: fits
    from: Part
    to: Vehicle
    cardinality: many_to_many
    properties:
      fitment_notes:
        type: string
        optional: true
      verified:
        type: bool
        default: false
      source:
        type: string
        enum: [catalog, user_report, oem_cross_ref, ai_inferred, property_match, shared_neighbors]
      confidence:
        type: float
        optional: true
    description: "Part fits a specific vehicle"
    inverse: fitted_parts

  - name: replaces
    from: Part
    to: Part
    cardinality: many_to_many
    properties:
      direction:
        type: string
        enum: [upgrade, downgrade, equivalent]
      confidence:
        type: float
    description: "Part can replace another part"
```

### RelationshipSchema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | **yes** | — | Unique relationship name |
| `from` | string | **yes** | — | Source entity type name |
| `to` | string | **yes** | — | Target entity type name |
| `cardinality` | string | no | `"many_to_many"` | Cardinality constraint |
| `properties` | dict | no | `{}` | Edge property definitions (same schema as entity properties) |
| `description` | string | no | `null` | Human-readable description |
| `inverse` | string | no | `null` | Name for the reverse traversal direction |
| `is_hierarchy` | bool | no | `false` | Mark as a hierarchical relationship |

**Notes:**
- `from` and `to` must reference entity type names defined in `entity_types`.
- Edge `properties` use the same `PropertySchema` as entity properties.
- `inverse` enables traversing the relationship in reverse by name.

---

## named_queries

A dict of declarative traversal patterns. Each query defines an entry point and a sequence of traversal steps.

```yaml
named_queries:
  parts_for_vehicle:
    description: "Find all parts that fit a specific vehicle"
    entry_point: Vehicle
    traversal:
      - relationship: fits
        direction: incoming
        filter:
          verified: true
    returns: "list[Part]"

  compatible_replacements:
    description: "Find replacement parts that also fit the same vehicle"
    entry_point: Part
    traversal:
      - relationship: replaces
        direction: both
        filter:
          direction: [equivalent, upgrade]
      - relationship: fits
        direction: outgoing
        constraint: "target.vehicle_id == $vehicle_id"
    returns: "list[Part]"
```

### NamedQuerySchema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `description` | string | no | `null` | Human-readable description |
| `entry_point` | string | **yes** | — | Entity type to start the traversal from |
| `traversal` | list | **yes** | — | Sequence of traversal steps |
| `returns` | string | **yes** | — | Description of the return type |

### TraversalStep

Each step in the traversal sequence:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `relationship` | string or list[string] | **yes** | — | Relationship name(s) to traverse. A list fans out across all listed types and merges results. |
| `direction` | string | no | `"outgoing"` | `outgoing`, `incoming`, or `both` |
| `filter` | dict | no | `null` | Property filters on edges or target entities |
| `constraint` | string | no | `null` | Constraint expression to apply during traversal |
| `max_depth` | int | no | `1` | BFS depth for this step (1 = direct neighbors only). Results include all entities from depth 1 through max_depth. |

**Direction semantics:**
- `outgoing`: Follow edges from entry point (source → target)
- `incoming`: Follow edges into entry point (target → source)
- `both`: Follow edges in either direction

---

## constraints

A list of validation rules evaluated during `cruxible_evaluate`.

```yaml
constraints:
  - name: replacement_same_category
    rule: "replaces.from.category == replaces.to.category"
    severity: warning
    description: "Replacement parts should be in the same category"
```

### ConstraintSchema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | **yes** | — | Unique constraint name |
| `rule` | string | **yes** | — | Rule expression (see syntax below) |
| `severity` | string | no | `"warning"` | `warning` or `error` |
| `description` | string | no | `null` | Human-readable description |

### Rule Syntax

Constraints compare properties across relationship endpoints:

```
RELATIONSHIP.FROM.property == RELATIONSHIP.TO.property
```

- `RELATIONSHIP`: The relationship name (e.g., `replaces`)
- `FROM`: The source entity's property
- `TO`: The target entity's property
- Identifiers may contain letters, digits, underscores, and hyphens

**Example:** `replaces.from.category == replaces.to.category` — flags any `replaces` edge where the source and target parts have different categories.

---

## ingestion

A dict of named mappings that tell Core how to load CSV/JSON data into entities and relationships.

```yaml
ingestion:
  vehicles:
    entity_type: Vehicle
    file_pattern: "vehicles*.csv"
    id_column: vehicle_id

  parts:
    entity_type: Part
    file_pattern: "parts*.csv"
    id_column: part_number

  fitments:
    relationship_type: fits
    file_pattern: "fitments*.csv"
    from_column: part_number
    to_column: vehicle_id
```

### IngestionMapping

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `description` | string | no | `null` | Human-readable description of what data this mapping expects |
| `entity_type` | string | conditional | `null` | Entity type to ingest (mutually exclusive with `relationship_type`) |
| `relationship_type` | string | conditional | `null` | Relationship type to ingest (mutually exclusive with `entity_type`) |
| `file_pattern` | string | no | `null` | Glob pattern for matching data files |
| `id_column` | string | conditional | `null` | Column containing entity IDs (required for entity mappings) |
| `from_column` | string | conditional | `null` | Column containing source entity IDs (required for relationship mappings) |
| `to_column` | string | conditional | `null` | Column containing target entity IDs (required for relationship mappings) |
| `column_map` | dict | no | `{}` | Rename CSV columns to property names: `{csv_column: property_name}` |

**Rules:**
- Exactly one of `entity_type` or `relationship_type` must be set.
- Entity mappings require `id_column`.
- Relationship mappings require both `from_column` and `to_column`.
- `column_map` renames CSV columns to match property names in the schema.
- Columns not in `column_map` map by name if they match a schema property.

---

## Full Example

The complete drug-interactions demo config (`demos/drug-interactions/config.yaml`) demonstrates all sections:

```yaml
name: drug_interactions_demo
description: >
  Clinical drug interaction graph. 46 drugs across 6 therapeutic
  classes plus 6 CYP450 enzymes.

entity_types:
  Drug:
    description: A pharmaceutical drug from DDinter and/or CYP450 datasets.
    properties:
      drug_id:
        type: string
        primary_key: true
        description: Lowercase normalized drug name
      name:
        type: string
        description: Display name of the drug
      atc_code:
        type: string
        optional: true
        description: ATC level-1 code(s)
      therapeutic_class:
        type: string
        optional: true

  Enzyme:
    description: A CYP450 metabolic enzyme that processes drugs.
    properties:
      enzyme_id:
        type: string
        primary_key: true
        description: Enzyme identifier (e.g. cyp3a4)
      name:
        type: string
        description: Standard enzyme name (e.g. CYP3A4)
      family:
        type: string
        description: Enzyme family (CYP450)

relationships:
  - name: interacts_with
    description: Known drug-drug interaction from DDinter database.
    from: Drug
    to: Drug
    cardinality: many
    properties:
      severity:
        type: string
        description: Interaction severity (Major/Moderate/Minor/Unknown)

  - name: metabolized_by
    description: Drug is a substrate of this CYP450 enzyme.
    from: Drug
    to: Enzyme
    cardinality: many
    properties:
      source:
        type: string
        description: Data source for this relationship

  - name: inhibits
    description: Drug inhibits this CYP450 enzyme (AI-inferred).
    from: Drug
    to: Enzyme
    cardinality: many
    properties:
      confidence:
        type: float
        description: Confidence score 0.0-1.0
      evidence:
        type: string
      source:
        type: string

  - name: same_class
    description: Two drugs in the same therapeutic class.
    from: Drug
    to: Drug
    cardinality: many
    properties:
      therapeutic_class:
        type: string

named_queries:
  check_interactions:
    description: "What drugs interact with this one, and how severe?"
    entry_point: Drug
    returns: Drug
    traversal:
      - relationship: interacts_with
        direction: both

  find_mechanism:
    description: "Why do these two drugs interact? Trace through shared enzymes."
    entry_point: Drug
    returns: Drug
    traversal:
      - relationship: metabolized_by
        direction: outgoing
      - relationship: metabolized_by
        direction: incoming

  suggest_alternative:
    description: "Find drugs in the same class metabolized by different enzymes."
    entry_point: Drug
    returns: Drug
    traversal:
      - relationship: same_class
        direction: both
      - relationship: metabolized_by
        direction: outgoing

constraints:
  - name: no_self_interaction
    description: A drug should not interact with itself.
    rule: "interacts_with.FROM.drug_id != interacts_with.TO.drug_id"
    severity: error

ingestion:
  drugs:
    description: Drug entities from combined DDinter + CYP450 dataset
    entity_type: Drug
    id_column: drug_id
  enzymes:
    description: CYP450 enzyme entities
    entity_type: Enzyme
    id_column: enzyme_id
  interactions:
    description: Drug-drug interactions from DDinter
    relationship_type: interacts_with
    from_column: drug_id_a
    to_column: drug_id_b
```
