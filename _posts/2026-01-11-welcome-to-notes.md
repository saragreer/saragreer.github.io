---
layout: post
title: "Welcome to Notes"
date: 2026-01-11 12:00:00 -0600
---

I've been wanting a simple way to share quick thoughts and interesting links online. After exploring various CMS options and blogging platforms, I decided to build something custom using Jekyll and GitHub Pages.

## What I Built

This Notes section is powered by an email-to-post system that converts emails into blog posts automatically:

- I send an email to a dedicated email address
- A GitHub Action runs hourly and checks for new emails
- The email subject becomes the post title
- The email body becomes the post content
- The post is automatically published to this site

## The Stack

- **Jekyll** with the Minima theme for a clean, minimal design
- **Python script** that connects via IMAP to fetch and parse emails
- **GitHub Actions** for automation (runs hourly or on manual trigger)
- **GitHub Pages** for free hosting with automatic builds

## Why This Approach?

The beauty of this setup is that I can create posts from anywhere - my phone, tablet, or computer - using my regular email app. No need to log into a CMS, write markdown manually, or even have a text editor open. Just compose and send an email.

It's also completely free to run and requires no server maintenance. Everything is handled by GitHub's infrastructure.

Looking forward to sharing more notes here!
