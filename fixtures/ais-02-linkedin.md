--- meta ---
fixture_id: ais-02-linkedin
pillar: ai_for_shippers
format: linkedin_post
source: manual
--- note ---
Small workflow change: stopped pasting task descriptions into AI sessions
and started pasting the acceptance criteria instead, the "what done looks
like" list. Redo rate dropped noticeably within a week. Fifteen years of
writing acceptance criteria for teams transfers directly.
--- golden ---
One small change to how I hand work to a model, and the redo rate dropped within a week. I stopped pasting task descriptions and started pasting acceptance criteria, the plain list of what done looks like.

Task descriptions tell the model what to do, and it does something. Acceptance criteria tell it how the work will be judged, and it aims. The difference in output was large enough that I went back and reran two older tasks just to check I wasn't fooling myself. Same model, same codebase, better landings.

The funny part is that nothing here is new. I have spent fifteen years writing acceptance criteria so that human teams would stop guessing what the ticket meant. The skill transferred whole, no adaptation needed, which makes me think the bottleneck was never the model's ability to write code.

I'm not sure if you'd agree, but most of what people call prompt engineering looks a lot like product management with the meetings removed. What else transfers whole?
