// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { NavLink, useNavigate } from "react-router-dom"
import {
  MessageSquare,
  BarChart3,
  Ticket,
  MoreVertical,
  FlaskConical,
  LogOut,
  Sparkles,
  UserCircle,
} from "lucide-react"
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
import { useState } from "react"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"
import { useAuth } from "@/hooks/useAuth"

const baseLinks = [
  { to: "/", label: "Workspace", icon: MessageSquare },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
]
// Tickets dashboard is a demo feature; production wires its own ITSM.
const demoLink = { to: "/tickets", label: "Tickets", icon: Ticket }

export function NavBar() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { ticketing, testData } = useDemoFeatures()
  const { isAuthenticated, signOut, profile } = useAuth()

  const links = ticketing ? [baseLinks[0], demoLink, baseLinks[1]] : baseLinks

  // Identity chip: derive the inbound IdP from the id_token issuer so it's
  // self-evident which provider authenticated this session (Entra / Okta / Cognito).
  const iss = (profile?.iss as string) || ""
  const idp = iss.includes("login.microsoftonline.com")
    ? "Microsoft Entra ID"
    : iss.includes("okta.com")
      ? "Okta"
      : iss.includes("cognito")
        ? "Amazon Cognito"
        : iss
          ? "OIDC"
          : null
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
    <nav className="flex-none border-b bg-background/80 backdrop-blur-md px-4 h-14 flex items-center gap-1 text-sm">
      <span className="mr-4 flex items-center gap-2 font-semibold tracking-tight text-foreground">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Sparkles size={15} />
        </span>
        ERP Agent
      </span>
      {links.map(l => (
        <NavLink
          key={l.to}
          to={l.to}
          end={l.to === "/"}
          className={({ isActive }) =>
            `flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-colors ${
              isActive
                ? "bg-accent text-accent-foreground font-medium"
                : "text-muted-foreground hover:text-foreground hover:bg-accent/60"
            }`
          }
        >
          <l.icon size={14} />
          {l.label}
        </NavLink>
      ))}

      <div className="ml-auto flex items-center gap-2">
        {testData && (
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <button className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                <MoreVertical size={16} />
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-40 p-1">
              <button
                className="flex items-center gap-2 w-full px-2 py-1.5 text-sm text-foreground hover:bg-accent rounded-md transition-colors"
                onClick={() => {
                  navigate("/test-data")
                  setOpen(false)
                }}
              >
                <FlaskConical size={14} />
                Test Data
              </button>
            </PopoverContent>
          </Popover>
        )}

        {isAuthenticated && idp && (
          <Popover>
            <PopoverTrigger asChild>
              <button
                title="Signed-in identity"
                className="flex items-center gap-1.5 px-2 py-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                <UserCircle size={15} />
                <span className="hidden sm:inline max-w-[14rem] truncate">{displayName}</span>
                <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] font-medium text-accent-foreground">
                  {idp}
                </span>
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-3 text-xs">
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

        {isAuthenticated && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button className="flex items-center gap-1.5 px-2 py-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                <LogOut size={14} />
                Logout
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
