# Eval results

Raw output of the evals, so the numbers in the docs can be checked.

Run on 2026-11-02 on commit `d724cdc`: AMD Ryzen 5 PRO 4650U, CPU-only inference
in a 7.8 GB Docker VM.

| File | Command | Data |
|---|---|---|
| `retrieval_2026-11-02.txt` | `python -m eval.retrieval_eval` | The owner's private store (42 records). Prints aggregates only, no health values. |
| `answer_<model>_2026-11-02.txt` | `python -m eval.answer_eval --model <model> --repeat 3 --json <file>` | Fictional cases from `answer_cases.json`. |
| `answer_<model>_2026-11-02.json` | The same run | Each answer and its scores, all from fictional data. |

## Limits

- **Retrieval:** the questions are labelled for one person's records, so a clean
  clone cannot reproduce the run. There are 25 questions, and the operating point
  was chosen and reported on the same ones, with no held-out set.
- **Answers:** sampling is not seeded, so a re-run gives somewhat different counts.
  The scoring cannot catch a wrong claim built from correct numbers.
- **Latency:** these runs are not cold, so most of each prompt comes from Ollama's
  cache. Do not use their times as reply times. The laptop also appears to have
  slept for about an hour during the `qwen2.5:1.5b` run, which distorts that run's
  timing further but not its answers.
