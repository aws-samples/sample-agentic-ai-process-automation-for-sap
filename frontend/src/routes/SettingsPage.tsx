// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import { useFreshToken } from "@/hooks/useFreshToken"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Banner, EmptyState, PageBody, PageHeader, PageLoader } from "@/components/ui/page-chrome"
import { AutonomyGovernor } from "@/components/AutonomyGovernor"
import { fetchRuntimeConfig, saveRuntimeConfig, type ConfigPatch } from "@/services/configService"

/**
 * Operator settings — the values the SOP corpus cites, editable without a deploy.
 *
 * Every field here is an *override*: empty means "use what this deployment shipped",
 * which the placeholder names. That is what makes a change visible at a glance and
 * what makes reverting expressible — clearing a field deletes the row rather than
 * storing the default a second time.
 *
 * A tolerance decides whether an invoice auto-posts, so the API validates every
 * write independently. The client-side range check below is there to keep the form
 * from offering a value the API will refuse, not to be the gate.
 */

/** `namespace:key` — flat so one draft map covers contacts and every skill's constants. */
type FieldId = string

const contactField = (key: string): FieldId => `contact:${key}`
const constantField = (skill: string, symbol: string): FieldId => `constant:${skill}:${symbol}`

/** Deployed value for a symbol, shown as the placeholder an empty field falls back to. */
function overrideText(value: string | number | undefined): string {
  return value === undefined ? "" : String(value)
}

export default function SettingsPage() {
  const auth = useAuth()
  const getFreshTokens = useFreshToken()
  const [draft, setDraft] = useState<Record<FieldId, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const configQuery = useQuery({
    queryKey: ["runtime-config"],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchRuntimeConfig(idToken)
    },
    enabled: auth.isAuthenticated,
  })
  const config = configQuery.data

  // Persisted override per field, so a field is dirty exactly when it differs from
  // what the table holds — not from what is deployed.
  const persisted = useMemo(() => {
    const map: Record<FieldId, string> = {}
    if (!config) return map
    for (const [key, value] of Object.entries(config.overrides.contacts)) {
      map[contactField(key)] = overrideText(value)
    }
    for (const [skill, symbols] of Object.entries(config.overrides.constants)) {
      for (const [symbol, value] of Object.entries(symbols)) {
        map[constantField(skill, symbol)] = overrideText(value)
      }
    }
    return map
  }, [config])

  const value = (id: FieldId) => draft[id] ?? persisted[id] ?? ""
  const isOverridden = (id: FieldId) => value(id).trim() !== ""
  const set = (id: FieldId, next: string) => setDraft(prev => ({ ...prev, [id]: next }))

  const invalid = useMemo(() => {
    const problems: Record<FieldId, string> = {}
    if (!config) return problems
    for (const [skill, symbols] of Object.entries(config.defaults.constants)) {
      for (const symbol of Object.keys(symbols)) {
        const id = constantField(skill, symbol)
        const raw = (draft[id] ?? persisted[id] ?? "").trim()
        if (!raw) continue
        // No bound for the symbol means the API's fallback applies; refuse only what is
        // definitely wrong rather than inventing a client-side limit the API doesn't have.
        const [low, high] = config.bounds[symbol] ?? [0, Number.POSITIVE_INFINITY]
        const num = Number(raw)
        if (!Number.isFinite(num)) problems[id] = "Must be a number"
        else if (num < low || num > high) problems[id] = `Must be between ${low} and ${high}`
      }
    }
    return problems
  }, [config, draft, persisted])

  const dirty = useMemo(
    () => Object.keys(draft).filter(id => draft[id].trim() !== (persisted[id] ?? "")),
    [draft, persisted]
  )
  const hasErrors = Object.keys(invalid).length > 0

  async function handleSave() {
    if (!config) return
    setSaving(true)
    setError(null)
    setSaved(null)
    try {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      const result = await saveRuntimeConfig(buildPatch(dirty, draft), idToken)
      setDraft({})
      await configQuery.refetch()
      setSaved(`Saved ${result.updated} change${result.updated === 1 ? "" : "s"}.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Autonomy, contacts and tolerances the agent's SOPs cite. Changes apply to the next case — no redeploy."
        actions={
          <>
            {dirty.length > 0 && (
              <Button variant="ghost" disabled={saving} onClick={() => setDraft({})}>
                Discard
              </Button>
            )}
            <Button disabled={saving || dirty.length === 0 || hasErrors} onClick={handleSave}>
              {saving ? "Saving…" : `Save${dirty.length ? ` (${dirty.length})` : ""}`}
            </Button>
          </>
        }
      />

      <PageBody className="grow space-y-8">
        {error && <Banner tone="danger">{error}</Banner>}
        {saved && <Banner tone="success">{saved}</Banner>}
        {hasErrors && (
          <Banner tone="attention">
            Some values are outside the range the agent accepts. Fix them before saving.
          </Banner>
        )}

        {configQuery.isLoading && <PageLoader label="Loading configuration…" />}
        {configQuery.error instanceof Error && (
          <Banner tone="danger">{configQuery.error.message}</Banner>
        )}

        {config && (
          <>
            <Section
              title="Notification contacts"
              description="Where the agent routes escalations. A SOP that writes {{CONTACT_AP_TEAM}} resolves to the AP team address below."
            >
              {Object.keys(config.defaults.contacts).length === 0 ? (
                <EmptyState
                  message="No contacts declared."
                  hint="Contacts come from the `contacts` block in cdk/config.yaml."
                />
              ) : (
                <FieldGrid>
                  {Object.entries(config.defaults.contacts).map(([key, deployed]) => {
                    const id = contactField(key)
                    return (
                      <Field
                        key={id}
                        id={id}
                        label={key.replace(/_/g, " ")}
                        hint={`{{CONTACT_${key.toUpperCase()}}}`}
                        overridden={isOverridden(id)}
                      >
                        <Input
                          id={id}
                          type="email"
                          placeholder={deployed}
                          value={value(id)}
                          onChange={e => set(id, e.target.value)}
                        />
                      </Field>
                    )
                  })}
                </FieldGrid>
              )}
            </Section>

            {Object.entries(config.defaults.constants).map(([skill, symbols]) =>
              Object.keys(symbols).length === 0 ? null : (
                <Section
                  key={skill}
                  title={`Tolerances — ${skill.replace(/_/g, " ")}`}
                  description="Thresholds the SOP compares against. A wider tolerance means more cases clear without review."
                >
                  <FieldGrid>
                    {Object.entries(symbols).map(([symbol, deployed]) => {
                      const id = constantField(skill, symbol)
                      const [low, high] = config.bounds[symbol] ?? [0, undefined]
                      return (
                        <Field
                          key={id}
                          id={id}
                          label={symbol}
                          hint={`Range ${low}–${high ?? "—"}`}
                          overridden={isOverridden(id)}
                          error={invalid[id]}
                        >
                          <Input
                            id={id}
                            type="number"
                            min={low}
                            max={high}
                            step="any"
                            aria-invalid={Boolean(invalid[id])}
                            placeholder={String(deployed)}
                            value={value(id)}
                            onChange={e => set(id, e.target.value)}
                          />
                        </Field>
                      )
                    })}
                  </FieldGrid>
                </Section>
              )
            )}
          </>
        )}

        {/* Outside the `config &&` guard on purpose: the autonomy switch must not be
            gated on /config loading. A deployment whose config endpoint is failing is
            exactly one where an operator may need to take the agent off auto. */}
        <AutonomyGovernor />
      </PageBody>
    </>
  )
}

/** Only dirty fields travel; a cleared field sends null so the row is deleted. */
export function buildPatch(dirty: FieldId[], draft: Record<FieldId, string>): ConfigPatch {
  const patch: ConfigPatch = {}
  for (const id of dirty) {
    const raw = draft[id].trim()
    const [namespace, ...rest] = id.split(":")
    if (namespace === "contact") {
      patch.contacts ??= {}
      patch.contacts[rest.join(":")] = raw === "" ? null : raw
    } else {
      const [skill, symbol] = rest
      patch.constants ??= {}
      patch.constants[skill] ??= {}
      patch.constants[skill][symbol] = raw === "" ? null : Number(raw)
    }
  }
  return patch
}

function Section({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-display text-sm font-semibold tracking-tight">{title}</h2>
        <p className="max-w-2xl text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  )
}

function FieldGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{children}</div>
}

function Field({
  id,
  label,
  hint,
  overridden,
  error,
  children,
}: {
  id: string
  label: string
  hint: string
  /** Marks a value that differs from the deployment — the only way an edit is visible. */
  overridden: boolean
  error?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 flex items-center gap-2 text-sm font-medium">
        <span className="truncate capitalize">{label}</span>
        {overridden && (
          <span className="flex-none rounded-sm bg-muted px-1 text-2xs uppercase tracking-wider text-muted-foreground">
            Overridden
          </span>
        )}
      </label>
      {children}
      <p className="mt-0.5 text-xs text-muted-foreground/70">
        {error ? <span className="text-destructive">{error}</span> : hint}
      </p>
    </div>
  )
}
