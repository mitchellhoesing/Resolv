# Resolv runs the whole issue-to-PR pipeline inside one ephemeral per-issue
# container: clone, context broker, coder, test run, and git push all happen
# here. CodeRabbit is NOT run in-container — it runs in the cloud on the PR
# after the push.
#
# The container must be launched with CAP_SYS_ADMIN so the test runner can
# `unshare --net` the untrusted test suite into an isolated network namespace:
#
#   docker run --rm --cap-add=SYS_ADMIN \
#     -e RESOLV_GITHUB_TOKEN -e RESOLV_ANTHROPIC_API_KEY \
#     resolv-sandbox:latest run --repo owner/name --issue 123

FROM python:3.12-slim

# git: clone + push. util-linux: `unshare` for network isolation.
# iproute2: `ip` to bring loopback up inside the new netns.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         git \
         ca-certificates \
         bash \
         util-linux \
         iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Editable install from a fixed path so config.py resolves /app/config/settings.toml.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY config/ ./config/

# resolv + runtime deps, plus the test runners target repos invoke.
RUN pip install --no-cache-dir -e . pytest tox

WORKDIR /workspace

ENTRYPOINT ["resolv"]
