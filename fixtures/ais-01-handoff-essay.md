--- meta ---
fixture_id: ais-01-handoff-essay
pillar: ai_for_shippers
format: substack_essay
source: manual
--- note ---
Workflow experiment: every project gets a PROJECT_OS.md and a decisions log,
and every AI coding session starts by reading them. Measured over two weeks:
rework after a session dropped from about 40 minutes to about 15. The model
stopped re-litigating settled decisions. Same convention I used for handover
docs on delivery teams for years, ported to a machine teammate. Wrote the
first decisions log on a delayed train with no wifi. Open question: how much
of the doc the model actually needs versus what I need to write to think
clearly.
--- golden ---
> Covered here: a PROJECT_OS.md and decisions-log convention for AI coding sessions, the measured drop in rework, and what handover docs from delivery teams look like ported to a machine teammate.

So the same model that wrote clean code on Monday spent Thursday arguing me back into a database choice we had already rejected, and I realized the problem was not the model. It had no way to know the decision was settled. Nothing in the session said so. I was starting every session with a colleague who had amnesia and blaming the colleague.

## The convention I ported

On delivery teams I spent years insisting on handover docs nobody wanted to write, one page that says what we decided and why, so the next person does not reopen closed questions. The old thing was a handover doc for the next engineer on rotation; here's how that's evolving, the next engineer is now a model, and it reads faster than any human I ever onboarded.

So every project got two files: a PROJECT_OS.md that says what this thing is and how it runs, and a decisions log that says what is settled. Every AI session begins by reading both. That's the whole workflow, and I wrote the first decisions log on a delayed train with no wifi, which turned out to be the ideal writing environment for it, since there was nothing to do but think.

## What the data showed

I measured rework for two weeks, the time spent undoing or redoing what a session produced. It dropped from about 40 minutes per session to about 15. Most of the recovered time came from one behavior change: the model stopped re-litigating settled decisions. It stopped proposing the rejected database, stopped restructuring modules whose shape was deliberate. The code generation was never the slow part. The arguing was.

That didn't work out as expected in one respect, but here's what I learned. I assumed the win would come from richer technical context, architecture diagrams, dependency maps. The decisions log, the least technical file in the repo, did nearly all the work. Judgment, written down, beat detail.

## The part I can't measure yet

I'm not sure if you'd agree, but I suspect half the value of these files has nothing to do with the model reading them. Writing "we decided X because Y" forces me to check that we actually decided, and that Y still holds. Some sessions the doc catches the drift before the model ever sees it.

Which leaves the question I can't answer yet: how much of the doc does the model need, and how much do I need to write in order to think clearly? The rework numbers can't separate those two. If you run a convention like this with a different split, tell me what you kept and what you cut, and I'm genuinely asking.
