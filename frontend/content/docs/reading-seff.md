---
title: Reading seff after a job finishes
category: GPUs and clusters
excerpt: seff tells you how much CPU and memory a finished job actually used, so your next request is closer to reality. It says nothing at all about GPUs.
order: 2
draft: false
---
When a job finishes, `seff` gives you the short version of what it actually used:

```
$ seff 12345
Job ID: 12345
State: COMPLETED (exit code 0)
Cores: 8
CPU Utilized: 02:41:12
CPU Efficiency: 41.9% of 06:24:00 core-walltime
Memory Utilized: 3.42 GB
Memory Efficiency: 10.7% of 32.00 GB
```

Two numbers matter here.

**CPU efficiency** compares the CPU time your job burned against the CPU time it reserved (cores multiplied by walltime). Well under 100% usually means one of two things: you asked for more cores than the code can use, or the job spent its time waiting on disk rather than computing. The fix for the first is to ask for fewer cores. The fix for the second is not a scheduler setting.

**Memory efficiency** compares peak resident memory against what you requested. This is the one that saves you queue time. If you asked for 32 GB and peaked at 3.4 GB, you have been queuing behind a much larger request than you needed, and the scheduler has been holding memory idle for you on a node someone else could have used.

## Array jobs

`seff` reports one task at a time. For an array, name the task:

```bash
seff 12345_7
```

If you want the whole array at once, `sacct` is the better tool:

```bash
sacct -j 12345 --format=JobID,Elapsed,MaxRSS,ReqMem,AllocCPUS,TotalCPU
```

`MaxRSS` is peak memory per task and `ReqMem` is what you asked for; comparing those two columns across every row shows you whether one task is driving the whole request or whether they are all the same size. Note that `MaxRSS` appears on the `.batch` and step rows rather than the parent job row, so do not be surprised when the top line is blank.

## seff says nothing about GPUs

This is the part that catches people. `seff` reports CPU and memory only. A job can sit on an A100 doing nothing for four hours and `seff` will still report a perfectly respectable CPU efficiency, because the CPU was busy feeding a GPU that was mostly idle.

To find out what the GPU did, you have to measure it while the job is running. The simplest way is to sample from inside the job script:

```bash
nvidia-smi --query-gpu=utilization.gpu,memory.used \
  --format=csv -l 60 > gpu_usage.csv &
NVSMI_PID=$!

# ... your actual job here ...

kill $NVSMI_PID
```

That writes one line a minute for the life of the job. Remember to kill it at the end, or the sampler keeps the job alive after your work is done and you pay walltime for nothing.

The other route is the cluster's own monitoring portal, which records this for you without changing the job script:

| Cluster | Where to look |
|---------|---------------|
| Narval | Metrix |
| Nibi | portal.nibi.sharcnet.ca |
| Trillium | my.scinet.utoronto.ca |

Either way, look at two things: whether GPU utilisation ever gets near 100%, and how much GPU memory the job actually touched. Low utilisation with low memory usually means the data pipeline is the bottleneck, not the GPU. High memory with low utilisation means the model fits but is waiting on something else.

The point of all of this is the next submission. A finished job tells you what to request next time: fewer cores, less memory, or a smaller GPU. Guessing high feels safe, but every gigabyte and every core you do not need is time spent in the queue.
