---
title: Why generated sbatch scripts go unchecked
description: A generated job script buries the per-task mapping in shell nobody reads. Generate a table of tasks instead and the mistakes become visible.
date: 2026-08-27
category: SLURM
excerpt: Same model, same guess, a completely different failure mode. The argument for generating a small table you can read instead of a long script you cannot.
image: /images/blog/2026-08-27-generated-sbatch-scripts-unchecked.png
imageAlt: The phrase "A table you can check." on a dark card, above an arrow running from a large amber block to a small blue one.
draft: false
---

A tool that turns a sentence into a job script does two things at once. It saves you an hour of scheduler syntax, and it hands you sixty lines of shell that you are not going to read.

The risk in that is not that the model gets it wrong sometimes. Everything gets it wrong sometimes, including the person typing. The risk is that the output is shaped so that being wrong is invisible.

## Why a generated sbatch script goes unchecked

A submission script for a batch of related runs is mostly furniture. Directives for the scheduler at the top, module loads, a bit of environment setup, a line that launches the program. Somewhere in the middle, four or five lines of it, sits the part that actually encodes what you asked for: the mapping from a task number to the parameters that task runs with.

Ask for a sweep of ten step sizes across three variants, and [SLURM](https://slurm.schedmd.com/) being what it is, you get something like this.

```bash
#!/bin/bash
#SBATCH --array=0-29
#SBATCH --partition=compute
#SBATCH --time=02:00:00

module load solver-env

STEPS=(0.01 0.02 0.05 0.10 0.20 0.50 1.00 2.00 5.00 10.00)
VARIANTS=(alpha beta gamma)

i=$SLURM_ARRAY_TASK_ID
step=${STEPS[$(( i % 10 ))]}
variant=${VARIANTS[$(( i / 10 ))]}

srun ./solver --step "$step" --variant "$variant" --out "run_${i}"
```

That fragment is correct. Confirming it is correct is the problem. You have to hold several things in your head at the same time: bash arrays count from zero, `0-29` is thirty tasks and not twenty-nine, the remainder picks the step whilst the integer division picks the variant, and those two roles swap if you write the arrays the other way round. Change the range to `1-30` and every task shifts by one without complaint. The last one asks for element thirty of a ten-element array, gets an empty string back, and either dies immediately or runs with a default you did not choose.

Reading that is a skill. It is not a difficult skill, but it is a specific one, and somebody who knows their own subject inside out can easily have had no reason to acquire it. So in practice the script is not checked. It is submitted. It queues. Any error surfaces hours later as a job that failed, or, worse, one that finished cleanly with the wrong numbers in it.

The second one is the expensive failure, and not because of the compute. A batch that crashes tells you something is wrong within a few minutes of starting. A batch where one task ran the variant you already had and skipped the one you actually wanted goes into your results directory looking exactly like every other batch. You find it, if you find it, at the point where two numbers disagree and you start working backwards.

## What the same job looks like as a table

Keep the model. Keep the guess. Change the shape of what it produces.

Instead of expanding "sweep the step over ten values for each of three variants" into shell, expand it into a table: one row per task, one column per parameter, values in plain sight.

```
task,step,variant
0,0.01,alpha
1,0.02,alpha
2,0.05,alpha
...
9,10.00,alpha
10,0.01,beta
...
19,10.00,beta
20,0.01,gamma
...
29,10.00,gamma
```

Same information, same thirty tasks, and now you can check it without knowing what `SLURM_ARRAY_TASK_ID` is. Thirty rows. Ten steps per variant. Three variant names, all present.

A duplicated setting is two identical rows. A forgotten configuration is a name that never appears. A batch that should have thirty tasks and has twenty-nine is a row count. Those are mistakes you catch by reading your own parameters, and reading your own parameters is a thing you can already do.

It also lets you check the expansion against the sentence you started from, which is a different question from whether the shell is valid. Say you asked for ten values spaced evenly on a log scale and rounded to two decimal places. Round 0.011 and 0.014 to two places and you have two rows reading 0.01, so the batch is nine distinct settings wearing ten rows. Nothing about that is a syntax error. It is visible in the table in about five seconds and invisible in the script forever.

## Review only works in the reviewer's own vocabulary

This is the part worth taking away, and it has nothing to do with SLURM.

Asking somebody to audit an artefact written in a language they do not speak is not review. It is ceremony. Everyone involved gets to feel that a check took place, the file gets an approving nod, and the thing that was wrong is exactly as wrong as it was before.

The model has not become more accurate here. The same wrong guess is available to it in both shapes. What changed is that in the second shape, being wrong is something a person can see, and the person who can see it is the one who knows what the run was for.

## Let the table drive a template that never changes

The script does not disappear. Something still has to be submitted. It stops being generated, though. Write it once, correctly, and have it read the table.

```bash
#!/bin/bash
#SBATCH --partition=compute
#SBATCH --time=02:00:00

module load solver-env

read -r step variant < <(
  awk -F, -v want="$SLURM_ARRAY_TASK_ID" '$1 == want { print $2, $3 }' tasks.csv
)

srun ./solver --step "$step" --variant "$variant" --out "run_${SLURM_ARRAY_TASK_ID}"
```

The array range comes off the file too, so the task count and the table can never disagree:

```bash
sbatch --array=0-$(( $(wc -l < tasks.csv) - 2 )) submit.sh
```

Now the part that changes between runs is the table, which is small and readable, and the part that does not change is a script you have already checked once. There is no month where this run's script differs from last month's in a way nobody noticed, because there is only one script. The index arithmetic that used to be worth staring at is gone, replaced by a lookup that either finds the row or does not.

## Keep the table on disk

Hold the table in memory, expand it, throw it away, and you get most of the benefit and none of the durable part. Write it to a file and three things follow.

It becomes the next run's input. Copy last month's table, change one column, submit that. The starting point for the new batch is the exact thing that ran before rather than a description you have to phrase again from scratch.

It goes under version control, so it can be diffed:

```
$ diff tasks-2026-07.csv tasks-2026-08.csv
12c12
< 11,0.02,beta
---
> 11,0.03,beta
```

One line, and you know precisely what is different about this batch. Try getting that from two sixty-line scripts where the module versions and the time limits also moved.

And it is a record of what was actually run, which is not the same thing as what you meant to run. Six months later, when a result looks odd, the table is a primary source and your memory is not.

## The one judgement no tool can make for you

There is a decision here that has to come from you, and it is worth naming rather than pretending it is handled.

You have to say which parameters vary from task to task and which stay constant across the whole batch. No tool can make that call, because it is a statement about your work rather than about the computing. Everything that varies goes in the per-task table. Everything fixed goes in the job description, stated once.

Get that split wrong in one direction and you have thirty tasks running the same case, because something that should have varied was declared fixed. Get it wrong in the other and you carry a column of thirty identical values, which is harmless but tells you nothing. Neither error is caught by the machine, and neither is subtle once you look at the table, which is the point: the table is where you notice.

It applies to the resources as much as to the science. If the large cases need four hours and the small ones need twenty minutes, the time limit is a per-task parameter and belongs in the table as a column. If every task wants the same walltime, it is part of the job description and saying it thirty times adds nothing. Same decision, and it is yours either way.

It is a lower bar than learning array index arithmetic, and it is expressed in the words you already use for your own work. It is still a bar. A post arguing for interfaces that are honest about what they ask of you should be honest about what this one asks.

## What this generalises to

Whenever a tool produces configuration on somebody's behalf, four things hold.

Prefer generating a small structured artefact the user can read over a large procedural one they cannot.

Let the structured artefact drive a fixed template, so the generated part stays small and the mechanical part is not rewritten each time and cannot drift.

Persist it rather than holding it in memory, so it can be an input next time, live in version control, be diffed against last time, and stand as a record of what ran.

Check that review happens in the reviewer's own vocabulary, because review in any other language is decoration.

None of this depends on a model being involved. A table is worth exactly as much when you type it into a spreadsheet yourself or emit it from a script of your own. The generation is not the interesting part. The shape is.

That is why [ClusterPilot](https://github.com/ju-pixel/clusterpilot) expands a plain-English description into a per-task table and then feeds it to a submission script that stays the same from one batch to the next. The table is the bit worth arguing about; the script around it is deliberately boring. If you build tools that generate configuration for other people, ask what the person on the other end would have to know to catch a mistake. When the answer is a skill they do not have, the shape is wrong, however good the guess underneath it happens to be.
