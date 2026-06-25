{{/*
Deterministic secret derivation from a single seed (ADR-012).

deriveSecret: sha256sum("<seed>:<id>") truncated to `length` (default 32).
The same (seed, id) always yields the same value, so a credential generated
here for Keycloak and the same id referenced by an app match automatically,
with nothing secret ever committed.

Usage:
  include "ownsuite.deriveSecret" (dict "seed" $seed "id" "keycloak-db" "length" 32)
*/}}
{{- define "ownsuite.deriveSecret" -}}
{{- $length := .length | default 32 -}}
{{- printf "%s:%s" .seed .id | sha256sum | trunc (int $length) -}}
{{- end -}}

{{/*
getSecret: honor an explicit override (by id) from .Values.secretOverrides if
present, otherwise derive from the seed.

Usage:
  include "ownsuite.getSecret" (dict "root" $ "id" "keycloak-admin" "length" 32)
*/}}
{{- define "ownsuite.getSecret" -}}
{{- $overrides := .root.Values.secretOverrides | default dict -}}
{{- $override := index $overrides .id -}}
{{- if $override -}}
{{- $override -}}
{{- else -}}
{{- include "ownsuite.deriveSecret" (dict "seed" .root.Values.secretSeed "id" .id "length" (.length | default 32)) -}}
{{- end -}}
{{- end -}}
