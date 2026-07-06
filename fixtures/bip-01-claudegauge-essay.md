--- meta ---
fixture_id: bip-01-claudegauge-essay
pillar: build_in_public
format: substack_essay
source: manual
--- note ---
ClaudeGauge v1 shipped. A local tracker for Claude usage sessions. Built it
over three weekends after hitting the usage wall mid-session twice in one
week. Stack: SQLite plus a single local page, no framework. First schema was
wrong: I tracked tokens when I should have tracked sessions, rebuilt it in
weekend two. Now I use ClaudeGauge to manage the sessions I use to build
ClaudeGauge. Second weekend it rained the whole time. Open question: whether
per-session budgeting changes how I scope work, or just when I stop.
--- golden ---
> Covered here: ClaudeGauge v1, a local Claude session tracker built on SQLite, the schema I got wrong, and what per-session budgeting is doing to how I scope work.

So I hit the Claude usage wall mid-session twice in one week, and honestly, I wasn't sure if that was a me problem or a tool problem. Losing the thread mid-flow costs more than the minutes suggest, because the context in my head evaporates faster than the session resets. Rather than keep guessing, I spent three weekends building ClaudeGauge, a local tracker for usage sessions, and shipped v1 this week.

## What I actually built it with

The stack is deliberately boring: SQLite and a single local page, no framework, nothing running that I have to babysit. I have shipped enough platforms to know that the tool you maintain at midnight should be the one with the fewest moving parts. The interesting decisions were never in the stack anyway. They were in what to count.

## The schema I got wrong

That didn't work out as expected the first weekend, but here's what I learned. I started by tracking tokens, because tokens felt like the real unit, the thing being metered. A week of my own data said otherwise. What I actually manage is sessions, the stretches of attention between walls, and a token count buried inside a session tells me nothing about when to stop or what to defer. So weekend two was a rebuild around sessions as the primary record, with tokens demoted to a detail. It rained the entire weekend, which removed my last excuse for not doing the migration properly.

The old way I budgeted this kind of work was a weekly hour count on a delivery plan, and here's how that's evolving: the budget is now attention between interruptions, not hours on a calendar. Same instinct, different unit.

## The loop I didn't plan for

I now use ClaudeGauge to manage the sessions I use to build ClaudeGauge. Not sure if that's impressive or concerning, and I have decided not to resolve the question. It does mean every improvement gets tested on the most demanding user I have access to, which is me at the end of a budget.

I'm not sure if you'd agree, but knowing exactly when a session will end has changed my scoping more than any productivity advice I have read this year. I cut work into wall-sized pieces now, and the pieces got better.

What I can't tell yet is whether per-session budgeting is changing what I choose to build, or only when I stop building for the day. I keep watching for the difference.

It's local, first version, rough edges included. If you track your sessions some other way, I want to hear what unit you count, and I'm genuinely asking.
