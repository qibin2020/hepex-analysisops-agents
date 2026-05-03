# Contract-Driven Analysis Skill

Use the public task prompt for scientific behavior and the submission contract
for output shape. If they appear to conflict, keep the contract's filenames,
types, and fields, and use the prompt to decide how to compute and explain the
result.

Do not infer hidden task-family rules from names such as Hyy, HZZ, Z peak, L1,
or L2. Instead, read the prompt and contract literally. Required outputs,
required fields, exact stage IDs, exact cut IDs, and exact sample names must
come from the provided prompt or contract.

All numeric values must be computed from the runtime inputs. If the visible
manifest is a subset, analyze that subset completely and state the limitation
honestly.
