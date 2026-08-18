// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { NavLink, useNavigate } from "react-router"
import {
  MessageSquare,
  BarChart3,
  Ticket,
  FlaskConical,
  LogOut,
  Sparkles,
  UserCircle,
  Sun,
  Moon,
  MonitorSmartphone,
  Rows3,
  Rows2,
  SlidersHorizontal,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { useAuth } from "react-oidc-context"
import { useQueryClient } from "@tanstack/react-query"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"
import { useTheme, type ThemePref } from "@/hooks/useTheme"
import { useDensity } from "@/hooks/useDensity"
import { getConfig } from "@/lib/config"
import { clearOperatorContext } from "@/lib/signOut"
import { AgentHeartbeat } from "@/components/AgentHeartbeat"
import { cn, ICON_CHROME } from "@/lib/utils"

const baseLinks = [
  { to: "/", label: "Workspace", icon: MessageSquare },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
]
// Tickets dashboard is a demo feature; production wires its own ITSM.
const demoLink = { to: "/tickets", label: "Tickets", icon: Ticket }

// One cycling button rather than a menu: every other row in the rail is a
// single-action row, and three states are cheap to walk. Dark comes first off the
// `system` default so the opening click visibly does something on a light OS.
const THEME_NEXT: Record<ThemePref, ThemePref> = {
  system: "dark",
  dark: "light",
  light: "system",
}

/** Name the IdP behind an `iss` claim, matching on the parsed host rather than a
 * substring of the whole URL — `.../okta.com/x` is a path, not an Okta issuer. */
export function idpLabel(iss: string): string | null {
  if (!iss) return null
  let host: string
  try {
    host = new URL(iss).hostname
  } catch {
    return "OIDC"
  }
  if (host === "login.microsoftonline.com") return "Microsoft Entra ID"
  if (host === "okta.com" || host.endsWith(".okta.com")) return "Okta"
  if (host.startsWith("cognito-idp.")) return "Amazon Cognito"
  return "OIDC"
}
const THEME_ICON: Record<ThemePref, LucideIcon> = {
  light: Sun,
  dark: Moon,
  system: MonitorSmartphone,
}
const THEME_LABEL: Record<ThemePref, string> = {
  light: "Light",
  dark: "Dark",
  system: "System",
}

/** Shared geometry for every rail row so icons stay on a single optical axis. */
export function itemClass(active = false) {
  return cn(
    "group/item relative flex min-h-8 w-full items-center justify-center rounded-md px-0 py-2",
    "text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sidebar-ring",
    active
      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
  )
}

/** Left-edge marker for the active route — the affordance a vertical rail reads best. */
function ActiveMarker({ active }: { active: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "absolute -left-2 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full transition-opacity",
        active ? "bg-sidebar-primary opacity-100" : "opacity-0"
      )}
    />
  )
}

/**
 * The rail's only labelling: a CSS-only tooltip on hover or focus. Kept out of the
 * accessibility tree because every row already carries an aria-label, and its text
 * is that same aria-label so the two never drift.
 */
export function RailTooltip({ label }: { label: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2",
        "whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs font-medium",
        "text-popover-foreground opacity-0 shadow-md transition-opacity",
        "group-hover/item:opacity-100 group-focus-visible/item:opacity-100 motion-reduce:transition-none"
      )}
    >
      {label}
    </span>
  )
}

function RailLink({ to, label, icon: Icon }: { to: string; label: string; icon: LucideIcon }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      aria-label={label}
      className={({ isActive }) => itemClass(isActive)}
    >
      {({ isActive }) => (
        <>
          <ActiveMarker active={isActive} />
          <Icon size={ICON_CHROME} className="flex-none" />
          <RailTooltip label={label} />
        </>
      )}
    </NavLink>
  )
}

function ThemeToggle({ pref, onChoose }: { pref: ThemePref; onChoose: (next: ThemePref) => void }) {
  const Icon = THEME_ICON[pref]
  const next = THEME_NEXT[pref]
  // The label names the *next* state so the control announces what it will do,
  // not what it already shows.
  const label = `Switch to ${THEME_LABEL[next].toLowerCase()} theme`
  return (
    <button aria-label={label} className={itemClass()} onClick={() => onChoose(next)}>
      <Icon size={ICON_CHROME} className="flex-none" />
      <RailTooltip label={label} />
    </button>
  )
}

export function SideRail() {
  const navigate = useNavigate()
  const { ticketing, testData } = useDemoFeatures()
  const auth = useAuth()
  const queryClient = useQueryClient()
  const profile = auth.user?.profile
  const { pref: theme, choose: chooseTheme } = useTheme()
  const { density, toggle: toggleDensity } = useDensity()
  const isCompact = density === "compact"
  const densityLabel = isCompact ? "Switch to comfortable density" : "Switch to compact density"

  const signOut = async () => {
    const { client_id, redirect_uri } = await getConfig()
    // Wipe before navigating, not from the unauthenticated effect alone: the redirect
    // can win the race against React's re-render, and the effect would then run in a
    // tab that is already unloading. `AutoSignin` still holds that path for a session
    // that expires without anyone clicking here; both routes call the same wipe.
    clearOperatorContext(queryClient)
    auth.signoutRedirect({ extraQueryParams: { client_id, logout_uri: redirect_uri } })
  }

  const links = ticketing ? [baseLinks[0], demoLink, baseLinks[1]] : baseLinks

  // Identity chip: derive the inbound IdP from the id_token issuer so it's
  // self-evident which provider authenticated this session (Entra / Okta / Cognito).
  const iss = (profile?.iss as string) || ""
  const idp = idpLabel(iss)
  const displayName =
    (profile?.name as string) ||
    (profile?.preferred_username as string) ||
    (profile?.email as string) ||
    (profile?.sub as string) ||
    "Unknown"
  const claimRows: [string, string | undefined][] = [
    ["Provider", idp ?? undefined],
    ["Name", profile?.name as string | undefined],
    ["Username", profile?.preferred_username as string | undefined],
    ["Email", profile?.email as string | undefined],
    ["Issuer", iss || undefined],
    ["Audience", (profile?.aud as string) || undefined],
    ["Subject", profile?.sub as string | undefined],
  ]

  return (
    <nav
      aria-label="Primary"
      className={cn(
        "z-30 flex w-[var(--rail-w)] flex-none flex-col border-r border-sidebar-border",
        "bg-sidebar text-sidebar-foreground"
      )}
    >
      <div className="flex h-[var(--band-h)] flex-none items-center justify-center border-b border-sidebar-border">
        <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Sparkles size={ICON_CHROME} />
        </span>
      </div>

      <AgentHeartbeat />

      {/* ponytail: no scroll container. `overflow-y: auto` forces `overflow-x` to
          compute as auto too, which would clip every tooltip at `left-full` — the
          rail's only labelling. The ceiling: at ten rows the content is ~400px, so a
          viewport short enough to overflow pushes the footer below the fold. Portal
          the tooltip and restore the scroll if the rail ever grows past that. */}
      <ul className="flex-1 space-y-1 px-2 py-3">
        {links.map(l => (
          <li key={l.to}>
            <RailLink to={l.to} label={l.label} icon={l.icon} />
          </li>
        ))}
      </ul>

      <div className="flex-none space-y-1 border-t border-sidebar-border px-2 py-2">
        {/* Below the divider with the other preference rows: settings changes how the
            agent behaves, but it is not somewhere an operator works. */}
        <RailLink to="/settings" label="Settings" icon={SlidersHorizontal} />

        <ThemeToggle pref={theme} onChoose={chooseTheme} />

        <button
          aria-label={densityLabel}
          aria-pressed={isCompact}
          className={itemClass()}
          onClick={toggleDensity}
        >
          {isCompact ? (
            <Rows3 size={ICON_CHROME} className="flex-none" />
          ) : (
            <Rows2 size={ICON_CHROME} className="flex-none" />
          )}
          <RailTooltip label={densityLabel} />
        </button>

        {testData && (
          <button
            aria-label="Test Data"
            className={itemClass()}
            onClick={() => navigate("/test-data")}
          >
            <FlaskConical size={ICON_CHROME} className="flex-none" />
            <RailTooltip label="Test Data" />
          </button>
        )}

        {auth.isAuthenticated && idp && (
          <Popover>
            <PopoverTrigger asChild>
              <button aria-label="Signed-in identity" className={itemClass()}>
                <UserCircle size={ICON_CHROME} className="flex-none" />
                <RailTooltip label={displayName} />
              </button>
            </PopoverTrigger>
            <PopoverContent side="right" align="end" className="w-80 p-3 text-xs">
              <div className="mb-2 font-semibold text-foreground">Signed-in identity</div>
              <dl className="space-y-1">
                {claimRows
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <div key={k} className="flex gap-2">
                      <dt className="w-20 flex-none text-muted-foreground">{k}</dt>
                      <dd className="min-w-0 break-all font-mono text-foreground">{v}</dd>
                    </div>
                  ))}
              </dl>
            </PopoverContent>
          </Popover>
        )}

        {auth.isAuthenticated && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button aria-label="Logout" className={itemClass()}>
                <LogOut size={ICON_CHROME} className="flex-none" />
                <RailTooltip label="Logout" />
              </button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Confirm Logout</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to log out? You will need to sign in again to access your
                  account.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={() => signOut()}>Confirm</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </nav>
  )
}
