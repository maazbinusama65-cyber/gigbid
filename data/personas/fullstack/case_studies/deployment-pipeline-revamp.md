# Deployment Pipeline Revamp

**Client industry:** Start-up  
**Completed:** 2023-12  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: releases were manual, took half a day, and failed often. They described what they wanted as a push-to-deploy automation.

## What I built

On the engineering side I put in place automated checks on every pull request.
Under the hood: Docker.
A key piece was cloud hosting with managed queues, storage and load balancing.
This is where Playwright came in.

## Outcome

Result: deploys in 7 minutes, ten a week instead of one, rollbacks in one click.

## Stack

Docker, Playwright

