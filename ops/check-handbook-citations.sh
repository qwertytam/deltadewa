#!/usr/bin/env bash
#
# Fail on citations into the handbook that cannot be verified.
#
# The monthly Handbook links workflow fetches every published-site URL this
# repo cites and asserts the #fragment resolves in the returned HTML. It only
# recognises `qwertytam.github.io` URLs, so a citation written against GitHub
# source instead is never checked at all — which is how a dead anchor into
# `HANDBOOK.md` survived in CHANGELOG.md long after that file became a stub.
#
# Verifying the source form is not worth the machinery it would take. GitHub
# renders blob pages client-side, so the headings are not in the HTML curl
# gets back, and GitHub's slugger disagrees with the one the published site
# uses: `## Rule 2 — Market Rally Rebalance Trigger` slugs to
# `rule-2--market-rally-rebalance-trigger` on GitHub and
# `rule-2-market-rally-rebalance-trigger` on the site. Checking both forms
# means maintaining two sluggers against two rendering pipelines.
#
# So this bans the unverifiable form instead of trying to verify it. Cite the
# published site and the monthly job covers you automatically.
#
# Runs in the PR gate: no network, no dependencies.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

self="$(basename "$0")"

# file:line:url for every GitHub-hosted handbook URL in the tree. -I keeps
# `Binary file ... matches` out of the results.
matches="$(
  grep -rnoIE 'https?://github\.com/qwertytam/deltadewa-handbook[^][:space:]")'"'"'<>]*' . \
    --exclude-dir=.git \
    --exclude-dir=.venv \
    --exclude-dir=node_modules \
    --exclude-dir=__pycache__ \
    --exclude="$self" \
    2>/dev/null || true
)"

failed=0

while IFS= read -r match; do
  [ -n "$match" ] || continue

  # Strip the trailing prose punctuation the URL character class lets through.
  url="$(printf '%s' "${match#*:*:}" | sed -E 's/[.,;:]+$//')"
  where="$(printf '%s' "$match" | cut -d: -f1,2)"

  case "$url" in
    *HANDBOOK.md*)
      echo "FAIL  retired stub        $where"
      echo "                          $url"
      echo "                          HANDBOOK.md is a redirect stub; its headings are gone."
      failed=1
      ;;
    */blob/*"#"*)
      echo "FAIL  unverifiable anchor $where"
      echo "                          $url"
      echo "                          Anchors into source are not checked by the monthly job."
      failed=1
      ;;
  esac
done <<< "$matches"

echo
if [ "$failed" -ne 0 ]; then
  cat <<'GUIDANCE'
Cite the published site instead:

  https://qwertytam.github.io/deltadewa-handbook/<part>/<page>/#<anchor>

The anchor is the heading slug: punctuation deleted, lowercased, runs of
whitespace and hyphens collapsed to one hyphen. An em dash is deleted, not
turned into a hyphen. A page whose title comes from front matter has no
anchor at all — cite it by its bare URL.

Site URLs are swept by .github/workflows/handbook-links.yml, so a citation
written this way is verified from then on. See docs/part-x-coverage.md.

A bare repo link with no fragment (https://github.com/qwertytam/deltadewa-handbook)
is fine — it points at the repository, not at content.
GUIDANCE
  exit 1
fi

echo "Handbook citations are all in the verifiable published-site form."
