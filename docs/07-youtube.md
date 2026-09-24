# YouTube

The manual driver ends with a file on your desktop and a trip to Studio. The
YouTube driver ends with the clip on the channel, scheduled for the slot the
factory already picked, with the question waiting in the comments.

Nothing uploads on its own. **You** press *Upload to YouTube* on Today, or
run `factory publish`. Agents cannot: the MCP publish tool stays behind
`--allow-publish`, and an upload is the one thing in this factory that
cannot be taken back.

## Setting it up, once per channel

1. **A Google Cloud project.** Create one, enable **YouTube Data API v3**
   and **YouTube Analytics API**, then create an OAuth client of type
   **Desktop app**. Download it and save it as `client_secrets.json` in the
   project folder. While the project's consent screen is in *Testing*, add
   your own Google account as a test user.
2. **Install the extra:** `pip install -e '.[youtube]'`.
3. **Connect the channel:** Settings → Channel → **Connect this channel**,
   or `factory youtube connect --channel main`. A browser opens on the
   machine running the server; sign in as *that channel's* account. The
   factory never sees the password.
4. **Switch the driver** for the channel from `manual` to `youtube`
   (Settings → Channel → publish driver).

`factory youtube status` says what is connected and as whom.
`factory youtube disconnect` forgets the token; the grant itself lives in
the Google account and is revoked at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions).

Both secrets stay out of git: `client_secrets.json` and
`channels/<id>/token.json`. One token per channel — authorise each while
signed in to that channel's account, or a clip lands on the wrong one.

## What an upload actually sends

| field | what goes |
|---|---|
| title | the clip's title, as approved |
| description | the description, then the hashtags and `#Shorts` |
| tags | the hashtags without their `#`, up to 15 |
| category | `publish.youtube_category_id` (24, Entertainment) |
| privacy | **private with a publishAt** — the next slot (06:00 Bangkok) |
| made for kids | `publish.youtube_made_for_kids`, false here |
| comment | the clip's pinned question, as a top comment |

So a clip goes up private and YouTube turns it public at the slot. Nothing
is ever uploaded straight to public unless `publish.youtube_privacy` is set
to `public` on purpose; `private` skips the schedule and leaves it to you.

The API **cannot pin a comment**. The comment is posted and the result says
so; pinning is two taps in Studio.

## What comes back

`factory pull-metrics` (or Clips → published) reads views and likes from
the Data API and average view percentage from Analytics. The swipe-away
figure is derived: `audienceWatchRatio` in the first 2% of the clip,
reported as `(1 - ratio) * 100`. It tracks the thing the strategy cares
about but it is not an official YouTube figure.

A **retitle** of a published clip is pushed to the video with
`videos.update`, so the gauge the console keeps — what each title
earned — matches what viewers saw. If the push fails, the clip says
*needs manual update* and the reason is in the event log.

## Quota

An upload costs **1600 units** of a default **10,000 a day**, so about
**six uploads a day** per Google Cloud project; reading metrics is cheap.
The quota resets at midnight Pacific. When it runs out the error says so in
those words, and the rest of the queue can wait — the clips are already
made.

## When it goes wrong

| what you see | what it means |
|---|---|
| `not connected … run factory youtube connect` | no token for that channel yet |
| `invalid_grant` | the token was revoked or expired; connect again |
| `quotaExceeded` | six uploads today already; it resets at midnight Pacific |
| `youtubeSignupRequired` | that Google account has no YouTube channel |
| the comment did not post | the channel does not accept comments from the API; the video is fine |

Events land in the log as `youtube.uploaded`, `youtube.connected`,
`youtube.retitled` and `youtube.comment_failed`, so Activity and the Team
feed show what happened without asking Studio.
