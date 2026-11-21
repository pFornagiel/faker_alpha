import { useEffect, useState } from "react"
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router"
import { useQuery } from "@tanstack/react-query"
import {
  BookOpen, Database, Files, Grid3x3, LayoutDashboard, Link2, Network, Radar, ScanSearch, Search,
} from "lucide-react"

import { api, type SearchResult } from "@/lib/api"
import { CampaignDot } from "@/components/common"
import { ErrorBoundary } from "@/components/error-boundary"
import { Button } from "@/components/ui/button"
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command"
import { Kbd } from "@/components/ui/kbd"
import { Separator } from "@/components/ui/separator"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarInset,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger, useSidebar,
} from "@/components/ui/sidebar"

const NAV = [
  {
    label: "Wyniki analizy",
    items: [
      { to: "/", label: "Przegląd kampanii", icon: LayoutDashboard, end: true },
      { to: "/materials", label: "Materiały", icon: Files },
      { to: "/links", label: "Powiązania (pary)", icon: Link2 },
      { to: "/graph", label: "Graf powiązań", icon: Network },
      { to: "/matrix", label: "Macierz podobieństwa", icon: Grid3x3 },
    ],
  },
  {
    label: "Działania",
    items: [
      { to: "/analyse", label: "Analizuj nowy materiał", icon: ScanSearch },
      { to: "/scanner", label: "Skaner źródeł", icon: Radar },
      { to: "/data", label: "Dane i eksport", icon: Database },
    ],
  },
  {
    label: "Wiedza",
    items: [{ to: "/methodology", label: "Metodyka", icon: BookOpen }],
  },
]

function AppSidebar() {
  const { setOpenMobile } = useSidebar()
  const { pathname } = useLocation()
  return (
    <Sidebar>
      <SidebarHeader>
        <Link to="/" className="flex items-center gap-2 px-2 py-1.5">
          <img src="/favicon.svg" alt="" className="size-5" />
          <div className="leading-tight">
            <div className="font-semibold">FakeTrace</div>
            <div className="text-xs text-muted-foreground">łączenie reklam-oszustw w kampanie</div>
          </div>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        {NAV.map((g) => (
          <SidebarGroup key={g.label}>
            <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {g.items.map((it) => (
                  <SidebarMenuItem key={it.to}>
                    <SidebarMenuButton
                      asChild
                      tooltip={it.label}
                      isActive={(it.end ? pathname === it.to : pathname.startsWith(it.to)) || (it.to === "/" && pathname.startsWith("/campaigns")) || (it.to === "/links" && pathname.startsWith("/pair"))}
                    >
                      <NavLink to={it.to} end={it.end} onClick={() => setOpenMobile(false)}>
                        <it.icon />
                        <span>{it.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <p className="px-2 text-xs text-muted-foreground">HackNation 2026 · NASK „Follow the Fake”</p>
      </SidebarFooter>
    </Sidebar>
  )
}

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v)
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms)
    return () => clearTimeout(t)
  }, [v, ms])
  return d
}

function GlobalSearch() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState("")
  const dq = useDebounced(q.trim(), 200)
  const navigate = useNavigate()
  const { data, isFetching } = useQuery<SearchResult>({
    queryKey: ["search", dq],
    queryFn: () => api.get<SearchResult>(`/api/search?q=${encodeURIComponent(dq)}`),
    enabled: dq.length >= 2,
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement))) {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
  const go = (to: string) => {
    setOpen(false)
    setQ("")
    navigate(to)
  }
  return (
    <>
      <Button variant="outline" size="sm" className="min-w-0 flex-1 justify-start text-muted-foreground sm:max-w-sm" onClick={() => setOpen(true)}>
        <Search />
        <span className="truncate">Szukaj w bazie…</span>
        <Kbd className="ml-auto hidden sm:inline-flex">/</Kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title="Szukaj w bazie" description="Domeny, identyfikatory, osoby, produkty, kampanie">
        {/* cmdk needs its <Command> root; results are already filtered by the server */}
        <Command shouldFilter={false}>
        <CommandInput placeholder="np. healthlinkq, 2012165449475163, Brzoska, C1…" value={q} onValueChange={setQ} />
        <CommandList>
          {dq.length < 2 && <div className="px-3 py-6 text-center text-sm text-muted-foreground">Wpisz co najmniej 2 znaki.</div>}
          {dq.length >= 2 && isFetching && !data && <div className="px-3 py-6 text-center text-sm text-muted-foreground">Szukam…</div>}
          {dq.length >= 2 && !isFetching && <CommandEmpty>Brak wyników dla „{dq}”.</CommandEmpty>}
          {data && data.campaigns.length > 0 && (
            <CommandGroup heading="Kampanie">
              {data.campaigns.map((c) => (
                <CommandItem key={c.id} value={`c-${c.id}`} onSelect={() => go(`/campaigns/${c.id}`)}>
                  <CampaignDot c={c} /> <span className="font-medium">{c.code}</span> <span className="truncate text-muted-foreground">{c.name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {data && data.traces.length > 0 && (
            <CommandGroup heading="Ślady (pokaż wszystkie materiały z tą wartością)">
              {data.traces.map((t) => (
                <CommandItem key={`${t.type}:${t.value}`} value={`t-${t.type}-${t.value}`} onSelect={() => go(`/trace?type=${encodeURIComponent(t.type)}&value=${encodeURIComponent(t.value)}`)}>
                  <span className="shrink-0 text-xs text-muted-foreground">{t.type_label}</span>
                  <span className={t.type === "person" ? "truncate text-sm" : "truncate font-mono text-xs"}>{t.display}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">w {t.n} mat.</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {data && data.materials.length > 0 && (
            <CommandGroup heading="Materiały">
              {data.materials.map((m) => (
                <CommandItem key={m.id} value={`m-${m.id}`} onSelect={() => go(`/materials/${m.id}`)}>
                  <CampaignDot c={m.campaign} />
                  <span className="shrink-0 font-medium">Materiał {m.name}</span>
                  <span className="truncate text-xs text-muted-foreground">{m.hits[0]?.field}: {m.hits[0]?.value}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
        </Command>
      </CommandDialog>
    </>
  )
}

export function AppLayout() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 h-5" />
          <GlobalSearch />
        </header>
        <div className="mx-auto w-full max-w-7xl min-w-0 space-y-6 p-4 md:p-6">
          <ErrorBoundary resetKey={pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
