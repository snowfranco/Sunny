--- meta ---
fixture_id: bip-04-escalation-linkedin
pillar: build_in_public
format: linkedin_post
source: project_scan
--- note ---
[sunny/DECISIONS.md] Decision: reviewer retries capped at 2, refinement
conversations capped at 5 turns, then the system forces a human decision
instead of iterating. Rationale: an infinitely patient collaborator invites
endless bikeshedding; bounded loops make the human decide. Also decided:
export produces draft bundles only, no publish path in the codebase at all.
--- golden ---
The strangest design decision in my content pipeline is the one that makes it less capable on purpose. Every automated loop in it has a hard cap. The reviewer retries a failing draft twice, then stops and hands me its reasons. The refinement conversation takes five turns, then asks me to lock in or start over.

The early version had no caps, and working with it taught me something uncomfortable about myself. An infinitely patient collaborator invites infinite fiddling. I would push a sixth revision, then a ninth, not because the draft was getting better but because asking cost nothing. The bound is not there to protect the budget. It is there to make me decide.

Same reasoning behind a stricter call: the system has no publish path at all. Not disabled, absent. Every export is a draft bundle, and the last step is always me, on the platform, pressing the button with my own hand.

I'm not sure if you'd agree, but I keep wondering which other tools would improve if they were allowed to refuse a sixth iteration. What would you cap?
