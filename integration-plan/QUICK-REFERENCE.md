# Quick Reference — Industrial UCs + UC10 (v2)

> **Copy-paste card.** Assume you're at the repo root, `.env` is filled in, ADB 26ai reachable.

## Branch

```bash
cd ~/work/oci-defence-demo
git checkout develop && git pull
git checkout -b feature/uc10-requirements-intelligence
```

## Drop UC10 skeleton + replace scripts

```bash
cp -R integration-plan/uc10-skeleton industrial/10-requirements-intelligence
cp integration-plan/bootstrap-industrial.sh   scripts/
cp integration-plan/verify-coalition-vpd.sh   scripts/
chmod +x scripts/bootstrap-industrial.sh scripts/verify-coalition-vpd.sh
cat integration-plan/CLAUDE-md-additions.md >> CLAUDE.md
```

## Deploy

```bash
# Schema
./scripts/bootstrap-industrial.sh --shared-only         # only if v1 wasn't run
./scripts/bootstrap-industrial.sh --uc 10

# Synthetic sample data
./scripts/bootstrap-industrial.sh --load-uc10-samples
```

## Verify

```bash
# UC10 program isolation (the demo killer)
./scripts/verify-coalition-vpd.sh --uc 10

# Expected: PASS  Eurofighter ≠ FCAS  Mallory = 0
```

## Push agents

```bash
./scripts/bootstrap-industrial.sh --import-agents
```

## All-in-one (if you trust the steps)

```bash
./scripts/bootstrap-industrial.sh             # shared + UC01..03 + UC10 + agents
./scripts/bootstrap-industrial.sh --load-uc10-samples
./scripts/verify-coalition-vpd.sh
```

## Demo

Open `industrial/10-requirements-intelligence/demo/demo-script.md` and follow the 5 beats.

The mapping back to the RE-PPTX is in `industrial/10-requirements-intelligence/MAPPING-TO-RE-DECK.md`.

## Commit

```bash
git add industrial/10-requirements-intelligence/ \
        scripts/bootstrap-industrial.sh scripts/verify-coalition-vpd.sh \
        CLAUDE.md
git commit -m "feat(uc10): Requirements Intelligence for Defence Industry"
git push -u origin feature/uc10-requirements-intelligence
```

## Rollback (if needed)

UC10 is fully isolated — drop the 11 objects in section 6 of INTEGRATION-GUIDE.md and you're back to v1.
