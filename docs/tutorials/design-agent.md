# Design Agent Tutorial & Usage Guide

The **Design Agent** (`agents.design.DesignAgent`) is the initial entry point of the AeroForge pipeline. It takes plain natural language or structured engineering requirements and parses them into a standardized, validated `EngineeringSpec` that downstream agents (such as the Geometry Agent) consume.

---

## Quickstart

```python
from agents.design import DesignAgent, UnrecognizedRequirementError

agent = DesignAgent()

# Parse a natural language bracket requirement
spec = agent.parse("Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes.")

print("Component:", spec.component)
print("Parameters:", spec.parameters)
```

---

## Examples: Input Strings to `EngineeringSpec`

### 1. Standard Phase 1 Mounting Bracket

**Input:**
```text
"Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes."
```

**Produced `EngineeringSpec`:**
```python
EngineeringSpec(
    component="bracket",
    parameters={
        "length": 100.0,
        "width": 80.0,
        "thickness": 5.0,
        "hole_diameter": 8.0,
        "hole_count": 4.0,
    },
    requirements=[
        Requirement(name="length", value=100.0, unit="mm"),
        Requirement(name="width", value=80.0, unit="mm"),
        Requirement(name="thickness", value=5.0, unit="mm"),
        Requirement(name="hole_diameter", value=8.0, unit="mm"),
        Requirement(name="hole_count", value=4.0, unit=None),
    ],
    constraints=[
        Constraint(name="length", operator="==", value=100.0),
        Constraint(name="width", operator="==", value=80.0),
        Constraint(name="thickness", operator="==", value=5.0),
        Constraint(name="hole_diameter", operator="==", value=8.0),
        Constraint(name="hole_count", operator="==", value=4.0),
    ],
    objectives=[],
    metadata={
        "raw_requirement": "Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes.",
        "unit": "mm",
        "parser": "rule_based",
    },
)
```

---

### 2. Alternative Syntax (Named Parameters & Digit Holes)

**Input:**
```text
"Mounting bracket with length: 120, width: 60, thickness: 4, 2 holes of 6 mm diameter"
```

**Produced `EngineeringSpec`:**
```python
EngineeringSpec(
    component="bracket",
    parameters={
        "length": 120.0,
        "width": 60.0,
        "thickness": 4.0,
        "hole_diameter": 6.0,
        "hole_count": 2.0,
    },
    requirements=[
        Requirement(name="length", value=120.0, unit="mm"),
        Requirement(name="width", value=60.0, unit="mm"),
        Requirement(name="thickness", value=4.0, unit="mm"),
        Requirement(name="hole_diameter", value=6.0, unit="mm"),
        Requirement(name="hole_count", value=2.0, unit=None),
    ],
    constraints=[
        Constraint(name="length", operator="==", value=120.0),
        Constraint(name="width", operator="==", value=60.0),
        Constraint(name="thickness", operator="==", value=4.0),
        Constraint(name="hole_diameter", operator="==", value=6.0),
        Constraint(name="hole_count", operator="==", value=2.0),
    ],
    objectives=[],
    metadata={
        "raw_requirement": "Mounting bracket with length: 120, width: 60, thickness: 4, 2 holes of 6 mm diameter",
        "unit": "mm",
        "parser": "rule_based",
    },
)
```

---

### 3. Solid Bracket Without Holes

**Input:**
```text
"100 x 80 x 5 mm bracket with no holes"
```

**Produced `EngineeringSpec`:**
```python
EngineeringSpec(
    component="bracket",
    parameters={
        "length": 100.0,
        "width": 80.0,
        "thickness": 5.0,
        "hole_diameter": 0.0,
        "hole_count": 0.0,
    },
    requirements=[
        Requirement(name="length", value=100.0, unit="mm"),
        Requirement(name="width", value=80.0, unit="mm"),
        Requirement(name="thickness", value=5.0, unit="mm"),
    ],
    constraints=[
        Constraint(name="length", operator="==", value=100.0),
        Constraint(name="width", operator="==", value=80.0),
        Constraint(name="thickness", operator="==", value=5.0),
    ],
    objectives=[],
    metadata={
        "raw_requirement": "100 x 80 x 5 mm bracket with no holes",
        "unit": "mm",
        "parser": "rule_based",
    },
)
```

---

## Supported Input Formats

### 1. Dimension Notations
The parser supports multiple dimensional expressions:
- **3-Way Multipliers:** `100 x 80 x 5 mm`, `100x80x5mm`, `100 × 80 × 5 mm`, `100*80*5 mm`
- **Phrased:** `100 mm by 80 mm by 5 mm`
- **Named Key-Value:** `length: 100, width: 80, thickness: 5` (also supports aliases like `len`, `thick`, `height`, `depth`)
- **Number Types:** Integers (`100`), Decimals (`100.5 x 80.25 x 4.5 mm`)

### 2. Hole Notations
- **Word Numbers (up to twenty):** `four 8 mm holes`, `two 6 mm mounting holes`
- **Digit Numbers:** `4 8mm holes`, `4x 8 mm holes`
- **Descriptive:** `4 holes of 8 mm`, `4 holes with 8 mm diameter`, `4 holes, each 8 mm in diameter`
- **Key-Value:** `hole count: 4, hole diameter: 8 mm`
- **No Holes:** `no holes`, `without holes`, `0 holes`, or omitting hole phrases entirely.

---

## Error Handling & `UnrecognizedRequirementError`

The parser strictly enforces engineering validity and scoped support. `UnrecognizedRequirementError` is raised in the following conditions:

| Condition | Example Input | Reason |
|---|---|---|
| **Empty or whitespace input** | `""` or `"   "` | No specification provided. |
| **Non-engineering text** | `"Hello, can you help me?"` | No recognizable engineering parameters or component. |
| **Unsupported component** | `"Design a UAV wing with 2.5m span"` | Only `bracket` is supported in v0.1 milestone. |
| **Incomplete dimensions** | `"Create a 100 x 80 mm mounting bracket"` | Missing required thickness. |
| **Non-positive dimensions** | `"0 x 80 x 5 mm bracket"` | Dimensions must be strictly positive (`> 0`). |
| **Unparseable hole info** | `"100 x 80 x 5 mm bracket with some holes"` | Mentioned holes without valid count or diameter. |
| **Oversized hole diameter** | `"10 x 10 x 5 mm bracket with 4 50 mm holes"` | Hole diameter cannot equal or exceed bracket dimensions. |

---

## Integration Contract

Downstream consumers (e.g. `GeometryAgent`, `backend.pipeline`) should interact with the Design Agent using the public interface:

```python
from agents.design import DesignAgent, UnrecognizedRequirementError
from engineering.requirements.schema import EngineeringSpec
```
