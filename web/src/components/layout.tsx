import { useEffect, useState } from "react"
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router"
import { useQuery } from "@tanstack/react-query"
import {
  BarChart3, BookOpen, ChevronRight, Layers, LayoutGrid, Network, Plus, ScanSearch, Search,
} from "lucide-react"

import { api, type SearchResult } from "@/lib/api"
import { matLabel } from "@/lib/format"
import { CampaignDot } from "@/components/common"
import { ErrorBoundary } from "@/components/error-boundary"
import { Button } from "@/components/ui/button"
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command"
import { Kbd } from "@/components/ui/kbd"
import { Separator } from "@/components/ui/separator"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarHeader, SidebarInset,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger, useSidebar,
} from "@/components/ui/sidebar"

const NAV = [
  {
    to: "/",
    label: "Kampanie",
    hint: "Co połączono i dlaczego",
    icon: Layers,
    match: (p: string) => p === "/" || p.startsWith("/campaigns"),
  },
  {
    to: "/materials",
    label: "Materiały",
    hint: "Każda reklama i jej ślady",
    icon: LayoutGrid,
    match: (p: string) => p.startsWith("/materials") || p.startsWith("/trace"),
  },
  {
    to: "/relations",
    label: "Powiązania",
    hint: "Graf, macierz i tabela par",
    icon: Network,
    match: (p: string) => p.startsWith("/relations") || p.startsWith("/graph") || p.startsWith("/matrix") || p.startsWith("/links") || p.startsWith("/pair"),
  },
  {
    to: "/analyse",
    label: "Analiza i skaner",
    hint: "Nowy materiał, źródła, eksport",
    icon: ScanSearch,
    match: (p: string) => p.startsWith("/analyse") || p.startsWith("/scanner") || p.startsWith("/data"),
  },
  {
    to: "/metrics",
    label: "Metryki i metoda",
    hint: "Dendrogram, jakość, progi",
    icon: BarChart3,
    match: (p: string) => p.startsWith("/metrics") || p.startsWith("/methodology"),
  },
  {
    to: "/glossary",
    label: "Słowniczek",
    hint: "Co porównujemy i jakimi miarami",
    icon: BookOpen,
    match: (p: string) => p.startsWith("/glossary"),
  },
]

function AppSidebar() {
  const { setOpenMobile } = useSidebar()
  const { pathname } = useLocation()
  return (
    <Sidebar>
      <SidebarHeader className="border-b px-3 py-3">
        <Link to="/" className="flex items-center gap-3 px-1">
          <img src="/favicon.svg" alt="" className="size-7 shrink-0" />
          <div className="leading-tight">
            <div className="text-base font-semibold tracking-tight">FakeTrace</div>
            <div className="text-xs text-muted-foreground">Kampanie fałszywych reklam</div>
          </div>
        </Link>
      </SidebarHeader>
      <SidebarContent className="px-2 py-3">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu className="gap-1">
              {NAV.map((it) => (
                <SidebarMenuItem key={it.to}>
                  <SidebarMenuButton
                    asChild
                    size="lg"
                    tooltip={`${it.label} — ${it.hint}`}
                    isActive={it.match(pathname)}
                    className="h-auto py-2"
                  >
                    <NavLink to={it.to} onClick={() => setOpenMobile(false)}>
                      <it.icon className="size-[18px] shrink-0" />
                      <div className="min-w-0 leading-tight">
                        <div className="text-sm font-medium">{it.label}</div>
                        <div className="text-xs text-muted-foreground">{it.hint}</div>
                      </div>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t px-4 py-3">
        <p className="text-xs text-muted-foreground">HackNation 2026 · NASK „Follow the Fake”</p>
      </SidebarFooter>
    </Sidebar>
  )
}

function Breadcrumbs() {
  const { pathname } = useLocation()
  const crumbs: { label: string; to?: string }[] = []
  if (pathname.startsWith("/campaigns/")) {
    crumbs.push({ label: "Kampanie", to: "/" }, { label: `Kampania C${Number(pathname.split("/")[2]) + 1}` })
  } else if (pathname.startsWith("/materials/")) {
    crumbs.push({ label: "Materiały", to: "/materials" }, { label: `Materiał` })
  } else if (pathname.startsWith("/pair/")) {
    crumbs.push({ label: "Powiązania", to: "/relations" }, { label: "Porównanie pary" })
  } else if (pathname.startsWith("/trace")) {
    crumbs.push({ label: "Materiały", to: "/materials" }, { label: "Ślad" })
  }
  if (!crumbs.length) return null
  return (
    <nav aria-label="Ścieżka" className="hidden items-center gap-1.5 text-sm text-muted-foreground md:flex">
      {crumbs.map((c, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          {i > 0 && <ChevronRight className="size-3.5" />}
          {c.to ? <Link to={c.to} className="hover:text-foreground hover:underline underline-offset-4">{c.label}</Link> : <span className="font-medium text-foreground">{c.label}</span>}
        </span>
      ))}
    </nav>
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
      <Button variant="outline" className="h-9 min-w-0 flex-1 justify-start gap-2.5 text-sm font-normal text-muted-foreground sm:max-w-md" onClick={() => setOpen(true)}>
        <Search className="size-4" />
        <span className="truncate">Szukaj: domena, piksel, osoba, kampania…</span>
        <Kbd className="ml-auto hidden sm:inline-flex">/</Kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title="Szukaj w bazie" description="Domeny, identyfikatory, osoby, produkty, kampanie">
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
              <CommandGroup heading="Ślady — otwiera listę materiałów z tą wartością">
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
                    <span className="shrink-0 font-medium">Materiał {matLabel(m)}</span>
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
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background px-5">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="h-5" />
          <Breadcrumbs />
          <GlobalSearch />
          <Button asChild size="default" className="ml-auto shrink-0">
            <Link to="/analyse">
              <Plus className="size-4" />
              <span className="hidden sm:inline">Analizuj nowy materiał</span>
            </Link>
          </Button>
        </header>
        <div className="mx-auto w-full max-w-[1480px] min-w-0 space-y-6 p-5 md:px-8 md:py-7">
          <ErrorBoundary resetKey={pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
