# Suggested Commands — agent-zero-cortex

## Dev Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Testing
```bash
pytest tests/unit/ tests/wrapper/ -v   # unit + wrapper (default, no live Cortex needed)
pytest tests/unit/                     # pure-function tests only
pytest tests/wrapper/                  # Extension class glue tests only
pytest -m integration                  # real Cortex tests (requires live Cortex API)
```

## No linter/formatter configured
No ruff, black, flake8, or mypy config present in pyproject.toml. Follow existing code style manually.

## Deployment (from Mac → Proxmox LXC 500)
```bash
cd /Users/paolo/Documents/Projects
tar czf /tmp/agent-zero-cortex.tar.gz agent-zero-cortex/
scp /tmp/agent-zero-cortex.tar.gz root@192.168.1.5:/tmp/
ssh root@192.168.1.5 "pct push 500 /tmp/agent-zero-cortex.tar.gz /tmp/agent-zero-cortex.tar.gz"
ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  cd /tmp && tar xzf agent-zero-cortex.tar.gz
  PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
  EXT=/opt/agent-zero/data/python/extensions
  cp \$PLUGIN/monologue_start/_60_cortex_init.py       \$EXT/monologue_start/
  cp \$PLUGIN/monologue_end/_60_cortex_memorize.py     \$EXT/monologue_end/
  cp \$PLUGIN/message_loop_prompts_after/_60_cortex_recall.py \$EXT/message_loop_prompts_after/
'"
# No AZ restart needed for extension file updates
```

## Disable/Enable Cortex (no restart needed)
```bash
ssh root@192.168.1.5 "pct exec 500 -- sed -i 's/^CORTEX_ENABLED=.*/CORTEX_ENABLED=false/' /opt/agent-zero/.env"
```

## Check AZ logs for extension activity
```bash
ssh root@192.168.1.5 "pct exec 500 -- docker logs agent-zero --tail 50 2>&1" | grep -E "cortex_init|cortex_memorize|cortex_recall"
```

## Verify Cortex memories
```bash
curl -s -H "Authorization: Bearer $CORTEX_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST http://192.168.1.12:8001/v1/recall \
  -d '{"query": "your recent AZ task", "limit": 5}' | jq '.[] | {content, matched_via, score}'
```
