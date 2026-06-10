"""Demo runner: drive the advanced multi-agent tender-review graph end to end."""

import argparse
from pathlib import Path

from langgraph.types import Command

from harbourmaster.graph import graph
from harbourmaster.policies import active_policies
from harbourmaster.telemetry import init_telemetry

SAMPLE = Path(__file__).resolve().parents[1] / 'data' / 'sample_tender.md'


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the Harbourmaster demo review.')
    parser.add_argument(
        'sample',
        nargs='?',
        type=Path,
        default=SAMPLE,
        help='Path to a tender sample markdown file.',
    )
    return parser.parse_args()


def _print_findings(findings: dict) -> None:
    for finding in findings.get('findings', []):
        print(
            f"   - [{finding.get('risk_level', '?'):>6}] "
            f"{finding.get('clause_id', '?')} {finding.get('clause', '?')} "
            f"({finding.get('specialist', 'general')}): {finding.get('rationale', '')}"
        )


def main() -> None:
    init_telemetry()
    args = _parse_args()
    sample = args.sample
    if not sample.is_absolute():
        sample = Path.cwd() / sample

    tender = sample.read_text(encoding='utf-8')
    run_config = {'configurable': {'thread_id': 'demo-tender-001'}}

    print('=== Harbourmaster advanced tender review ===\n')
    print(f'Sample: {sample}\n')
    result = graph.invoke(
        {
            'tender_text': tender,
            'corporate_policies': active_policies(),
        },
        run_config,
    )

    if '__interrupt__' in result:
        payload = result['__interrupt__'][0].value
        print('[PAUSED] human oversight required')
        print(f"   overall_risk : {payload.get('overall_risk')}")
        print(f"   blocked      : {payload.get('blocked')}  {payload.get('block_reason', '')}")
        print(f"   clauses      : {len(payload.get('clauses', []))}")
        _print_findings(payload.get('findings', {}))
        print()

        decision = {
            'decision': 'approve',
            'reviewer': 'demo-user',
            'note': 'Approved — ask legal to negotiate indemnity and IP clauses.',
            'clause_notes': 'C2 cap indemnity; C5 retain background IP ownership.',
        }
        print(f"[REVIEW] {decision['decision']} by {decision['reviewer']}")
        print(f"         note: {decision['note']}\n")

        result = graph.invoke(Command(resume=decision), run_config)

    print('=== Final review note ===')
    print(result.get('draft_summary', '(none)'))
    print()
    print(f"Segmented clauses: {len(result.get('clauses', []))}")
    print(f"Verified findings: {len(result.get('verified_findings', []))}")
    print(f"Counter-clauses: {len(result.get('counter_clauses', []))}")
    print(
        f"Inspection reports captured: {len(result.get('inspection_reports', []))}"
        '  (these feed the audit trail / governance dashboard)'
    )


if __name__ == '__main__':
    main()
