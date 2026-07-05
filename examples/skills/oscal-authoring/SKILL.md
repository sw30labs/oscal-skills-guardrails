---
name: oscal-authoring
description: Use this skill when authoring or editing OSCAL documents (catalogs, profiles, SSPs, assessment results). Trigger on requests to write OSCAL JSON, map controls, or validate OSCAL structure.
license: Apache-2.0
allowed-tools: read_file grep glob
owner: governance
version: "1.0"
---

# oscal-authoring

## Overview

Author OSCAL artifacts consistently: catalogs, profiles, component definitions, SSPs,
and assessment results.

## Instructions

1. Identify the target OSCAL model and version (default 1.1.2).
2. Reuse existing UUIDs when editing; generate new UUIDv4 only for new objects.
3. Keep prop namespaces explicit; project-specific props use ns https://sw30labs.com/ns/osg.
4. Validate required fields per model before returning the document.
