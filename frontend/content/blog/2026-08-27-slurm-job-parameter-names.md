---
title: Stop naming your SLURM job parameters twice
description: Your script already declares the parameters it reads. Compare that against what your submission supplies and you catch the sweep that quietly used defaults.
date: 2026-08-27
category: SLURM
image: /images/blog/2026-08-27-slurm-job-parameter-names.png
imageAlt: The phrase "The job ran anyway." on a dark charcoal card, beside an amber terminal prompt.
draft: false
---

When you run a parameter sweep, something has to carry each task's settings from your submission into the script that does the work. The usual mechanisms are environment variables, the named values a scheduler puts in place before your script starts, or command line arguments. The usual question, and it is a reasonable one, is what to call those parameters and where to write that decision down.

You already wrote it down. It is in the script.

```python
NSAMPLES = int(os.environ.get("NSAMPLES", "1000"))
```

Or, in Julia:

```julia
const NSAMPLES = parse(Int, get(ENV, "NSAMPLES", "1000"))
```

One line, three facts: what the parameter is called, what it falls back to, and that it is an input rather than a working variable buried in the middle of a calculation. Nothing at submission time needs to invent a naming convention, because the code has already picked one.

## How parameters get into a SLURM job

A sweep on a cluster is usually a job array, one submission that runs the same script many times, once per set of settings. [SLURM](https://slurm.schedmd.com) hands each of those runs an index number, and it is up to you to turn the index into settings: task 7 gets this value, task 8 gets that one. Whatever you do with the index, the settings have to arrive inside the script somehow, and the two common answers are the environment and the argument list.

That is the whole mechanism, and it is also the point where the two halves of your run lose sight of each other.

## Neither side can see the other

Your script cannot see your submission. It reads whatever happens to be in the environment when it starts, and it has no way to know what you intended to set. Your submission cannot see your script. It puts names into the environment and has no way to know whether anything will look at them.

The only thing in the chain that sees both sides is whatever sits between you and the scheduler, because it holds your parameters in one hand and reads your script with the other. That is the position [ClusterPilot](https://github.com/ju-pixel/clusterpilot) sits in, which is why the comparison belongs there rather than in your script or in your submission.

Once something can read both sides, three disagreements become detectable.

## Three ways a SLURM submission and a script disagree

1. You supply something the script never reads. A typo, or a column left over from a previous sweep. The value is set, the script ignores it, and the run uses the default instead.
2. The script reads something with no default, and nothing supplies it. The job fails on the compute node, after you have waited in the queue for it.
3. The script reads something with a default, and nothing supplies it. The job runs. It succeeds. It writes output. The output is wrong, and nothing anywhere reports an error.

## The third one is the expensive one

The second case is irritating but honest. You lose the queue wait and you get a stack trace naming the thing you forgot. That is a fair trade.

The third case tells you nothing. Every signal you normally trust says the run was fine: exit status zero, output files present, sizes plausible, plots that plot. There is no error to grep for, because from the script's point of view nothing went wrong. It was handed no value, it used the default it was written with, and it did exactly what it was told. You find out when a number refuses to line up with another number, which might be next week, and might be never.

Comparing the two sides catches it before anything is submitted:

| Declared in the script | Supplied by the submission |
| --- | --- |
| `NSAMPLES` (default 1000) | 4000 |
| `NSTEPS` (no default) | 20000 |
| `SEED` (default 1) | 7 |
| `OUTDIR` (default `runs/`) | nothing supplied, unmatched |
| nothing declared | `NSAMPLESS` = 4000, unmatched |

Those last two rows are usually the same mistake seen from both ends. You meant to set `NSAMPLES`, you typed `NSAMPLESS`, and the run went ahead on 1000 instead of 4000.

## Environment variables are one convention, not the rule

This works when a script exposes its inputs in a way something else can read, and plenty of scripts do not. Command line arguments are just as common. A script can take both: one line that reads an environment variable and falls back to a positional argument if the variable is absent. Others read a config file, or get edited by hand between runs, and there is no line anywhere that says "this is an input".

So a check like this has to be an enhancement that works where it works, and stays quiet where it cannot identify a script's inputs. No check is acceptable; a wrong check is not. Nothing here should be read as a promise that every script declares its interface legibly, because that is not true.

## The part no tool can work out for you

There is one decision that stays yours, and I would rather say so than pretend otherwise. Which of your parameters vary from task to task, and which are the same for every task in the sweep? Nothing else in the chain can answer that. Both kinds look identical in the script and identical in the environment. The difference lives in your head, in what you meant the sweep to explore.

Everything that varies belongs in the per-task data, one row per run. Everything fixed belongs in the job description that covers the whole sweep. It is a lower bar than learning array syntax, and it is expressed in the terms you already think in rather than in scheduler syntax, but it is a real bar. A tool that claimed to make that split for you would be guessing.

## What to change

Stop deciding parameter names at submission time. They were decided when you wrote the script, in the line that reads each one, and that line is the only place the name, the default and the fact that it is an input all appear together. Read them off the script and let the two sides be compared before anything reaches the queue.

The bug worth designing against is not the job that crashes. A crash is a message. It is the job that succeeds with the wrong inputs, because that one arrives looking exactly like a result.
