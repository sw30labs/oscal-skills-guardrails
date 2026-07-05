---
name: langgraph-docs
description: Use this skill for requests related to LangGraph to fetch relevant documentation and provide accurate, up-to-date guidance. Trigger when the user asks about LangGraph concepts, APIs, or middleware.
license: MIT
allowed-tools: fetch_url read_file
owner: engineering
version: "1.0"
---

# langgraph-docs

## Overview

Fetch LangGraph documentation on demand instead of answering from stale memory.

## Instructions

1. Fetch the documentation index with the `fetch_url` tool: https://docs.langchain.com/llms.txt
2. Select the 2-4 most relevant pages for the question.
3. Fetch those pages and answer from them, direct answer first.
4. End with a References section listing the page URLs used.
