---
title: Asking for a slice of a GPU
category: GPUs and clusters
excerpt: Most Alliance clusters let you request part of a GPU instead of a whole one. The syntax per cluster, why slices queue faster, and when not to use them.
order: 3
draft: false
---
If your job does not need a whole A100 or H100, you can often ask for a piece of one. MIG is NVIDIA's way of splitting a single data-centre GPU into several smaller, independent GPUs, each with its own memory and compute share. From inside your job it looks like a normal, smaller GPU.

## How to request one

The syntax differs by cluster, and getting it wrong means the job is rejected or lands on hardware you did not intend:

| Cluster | Slice request | Whole GPU |
|---------|---------------|-----------|
| Narval (A100) | `--gres=gpu:a100_3g.20gb:1` or `a100_4g.20gb` | `--gres=gpu:a100:1` |
| Fir (H100) | `--gpus=nvidia_h100_80gb_hbm3_1g.10gb:1` (also `2g.20gb`, `3g.40gb`) | `--gpus=h100:1` |
| Nibi, Rorqual (H100) | `--gpus=h100_1g.10gb:1`, `h100_2g.20gb:1`, `h100_3g.40gb:1` | `--gpus=h100:1` |
| Trillium | no MIG | `--gpus-per-node=1` or `4` |

The number before the `g` is the compute share and the number after it is the memory. So `3g.40gb` is roughly three eighths of an H100 with 40 GB of GPU memory.

## Why a slice starts sooner

Two things work in your favour. The obvious one is that a smaller request fits in more gaps: the scheduler can start a `1g.10gb` job on a node that has no room for a whole GPU.

The less obvious one matters more. On the H100 clusters, roughly half the GPU nodes are configured as MIG nodes. Those nodes are a separate pool, and a request for a whole GPU cannot use them at all. Asking for a slice puts you in a queue that a large share of the jobs on the cluster are not competing for.

The practical effect is that a job which would have waited hours for a whole card can start in minutes, if it genuinely fits in the slice.

## When not to

**Multi-GPU or NVLink work.** Slices are independent GPUs with no fast interconnect between them. If your code scales across cards, or relies on NVLink bandwidth, a slice is the wrong shape.

**Trillium.** It has no MIG at all. Request whole GPUs there.

**Anything whose peak memory is close to the slice.** This is the failure mode worth taking seriously. A job that needs 24 GB and gets a `2g.20gb` slice does not queue faster; it queues, starts, runs for a while, and then dies with an out-of-memory error. You have spent the wait and got nothing. A slower queue and a completed job is the better trade every time.

Before you commit to a slice size, check your cluster's wiki for the per-slice CPU and memory maximums. Each slice comes with a cap on the CPU cores and system memory you may request alongside it, and asking for more than that cap is another way to have a job rejected.

If you do not know your job's peak GPU memory, [measure it once on a whole GPU](/docs/reading-seff) and then size the slice from the number you measured.

## Spread jobs across clusters

Priority on the Alliance systems is per cluster. Heavy usage on Narval does not lower your priority on Nibi or Fir. If your allocation covers more than one machine, request access to all of them in CCDB and submit where the queue is shortest. This is free queue time that most people leave on the table.

## What ClusterPilot does here

The GPU size choice stays yours. ClusterPilot generates the `--gres` or `--gpus` line to match the cluster you selected, but it does not decide between a slice and a whole card on your behalf, for the same reason it never picks your partition: that choice depends on what your job actually needs, and getting it wrong is expensive.

A GPU size picker on the F2 screen is on the roadmap. Follow [issue #30](https://github.com/ju-pixel/clusterpilot/issues/30) if you want to know when it lands.
