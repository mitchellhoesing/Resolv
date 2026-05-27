FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         git \
         curl \
         ca-certificates \
         bash \
         nodejs \
         npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest tox

RUN npm install -g @sourcegraph/scip-python

RUN curl -fsSL https://cli.coderabbit.ai/install.sh | bash

ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /workspace
