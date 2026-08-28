---
title: Where your jobs live on the cluster
category: GPUs and clusters
excerpt: ClusterPilot puts each job under your cluster's scratch path and syncs results home. Why that copy is temporary, and how to set the path correctly.
order: 1
draft: false
---
Every job ClusterPilot submits gets its own directory on the cluster, created under whatever path you put in the `scratch` setting for that cluster. Your project is rsynced into it, the job runs there, and when the job finishes the output files are rsynced back to your workstation.

That means the copy on the cluster is a working copy, not an archive. The permanent record is the one on your own machine.

```toml
[[clusters]]
name = "narval"
scratch = "/scratch/yourusername"
```

## Why scratch and not home

On Alliance clusters (`cluster_type = "drac"`), writing job output to your home directory is a mistake that bites in three different ways.

Home quotas are small, around 50 GB, and they are enforced. A job that fills the quota does not slow down, it fails partway through and leaves you with half a dataset. On Trillium the problem is more direct: home is mounted read-only on compute nodes, so a job that writes there does not run at all.

Scratch is the space designed for this. It is large, it is fast, and it is not backed up, which is the trade. Files there are removed by age: on the general-purpose clusters, anything older than about 60 days is purged. Nibi adds a soft quota of 1 TB with a 60-day grace period, so going over it is survivable but not indefinitely.

Read that purge window as a deadline, not a warning. Anything on scratch that you have not pulled home within two months is gone.

On Grex (`cluster_type = "grex"`) there is no scratch variable at all. Jobs live under your home directory or in your group's `/project` space, and the `scratch` setting in your config should point at one of those.

## Every cluster spells it differently

The awkward part is that the same idea has a different path on each machine:

| Cluster | Path to scratch |
|---------|-----------------|
| Fir | `$HOME/scratch` |
| Rorqual | `$HOME/links/scratch` |
| Narval | `$SCRATCH`, which is `/scratch/<user>` |

There is no rule that covers all of them, so do not guess. Log in once and run:

```bash
echo $SCRATCH
```

Put whatever it prints into the `scratch` field of that cluster's block in `~/.config/clusterpilot/config.toml`. Do this once per cluster, when you add it.

## When the sync comes back incomplete

Sometimes the automatic sync at job completion does not bring everything home. The usual cause is that the job wrote output somewhere the download filter skips, or the job finished while the daemon was not running.

The fix is on the F1 screen: select the job and use the manual sync button. It pulls back everything present in the job's directory on the cluster, not just the files the last automatic pass matched. If a file is still missing after that, check `download_excludes` in your config; the defaults skip source files and markdown on the assumption that you already have those locally, and an unusual output location can be caught by one of those patterns.

Do the manual sync sooner rather than later. Once the purge window closes, there is nothing left on the cluster to sync from, and no support ticket recovers it. If a job produced something you care about, get it home the same week.
