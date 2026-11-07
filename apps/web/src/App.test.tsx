// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from './App'
import { ApiContext } from './api/context'
import { createApi, type FetchLike } from './api/client'
import { AuthProvider } from './auth/AuthProvider'
import { createMockFetch } from './mock/server'

afterEach(cleanup)
// Autopilot's ~2 s countdown, shortened so the whole sample-business setup runs in a test.
vi.mock('./lib/autopilot', async (orig) => ({ ...(await orig<typeof import('./lib/autopilot')>()), AUTOPILOT_DELAY_MS: 20 }))
// jsdom has no layout; the chat pane scrolls its transcript.
Element.prototype.scrollTo ??= () => {}

function Probe() {
  return <output data-testid="path">{useLocation().pathname}</output>
}

function setup(path: string) {
  const mock = createMockFetch({ latencyMs: 0 })
  const calls: { url: string; method: string; body: unknown }[] = []
  const fetchSpy: FetchLike = (url, init) => {
    calls.push({ url, method: init?.method ?? 'GET', body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined })
    return mock(url, init)
  }
  render(
    <ApiContext.Provider value={createApi(fetchSpy)}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
          <Probe />
        </AuthProvider>
      </MemoryRouter>
    </ApiContext.Provider>,
  )
  return { calls, path: () => screen.getByTestId('path').textContent }
}

const type = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

async function signUp(email = 'dana@example.com') {
  await screen.findByRole('heading', { name: 'Create your account' })
  type('Your name', 'Dana')
  type('Email', email)
  type('Password', 'longenough')
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
}

describe('auth routes', () => {
  it.each(['/workplaces', '/workplaces/new', '/w/mock-1'])('sends a signed-out visitor on %s to /login', async (p) => {
    const t = setup(p)
    await screen.findByRole('heading', { name: 'Sign in' })
    expect(t.path()).toBe('/login')
  })

  it('shows the landing page at / without a store', async () => {
    const t = setup('/')
    expect(screen.getByRole('heading', { name: /Legal, lowest-cost schedules for hourly teams, in minutes/ })).toBeTruthy()
    expect(screen.getAllByRole('link', { name: 'Get started' }).length).toBe(1)
    await waitFor(() => expect(t.calls.some((c) => c.url.startsWith('/api/stores'))).toBe(false))
  })

  it('signup shows inline errors, then lands on /workplaces/new', async () => {
    const t = setup('/signup')
    await screen.findByRole('heading', { name: 'Create your account' })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Enter your name.')).toBeTruthy()
    expect(screen.getByText('Enter your email.')).toBeTruthy()
    type('Password', 'short')
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Use at least 8 characters.')).toBeTruthy()

    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    expect(t.path()).toBe('/workplaces/new')
    const req = t.calls.find((c) => c.url === '/api/auth/signup')
    expect(req?.body).toEqual({ name: 'Dana', email: 'dana@example.com', password: 'longenough' })
  })

  it('signup with a taken email says so on the email field', async () => {
    setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('heading', { name: 'Sign in' })
    fireEvent.click(screen.getAllByRole('link', { name: 'Create an account' })[0])
    await signUp()
    expect(await screen.findByText('An account with that email already exists.')).toBeTruthy()
  })

  it('login with the wrong password shows an inline error; sign out → sign in lands on /workplaces', async () => {
    const t = setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('heading', { name: 'Sign in' })
    type('Email', 'dana@example.com')
    type('Password', 'wrongpassword')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Wrong email or password.')).toBeTruthy()
    type('Password', 'longenough')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: 'My workplaces' })
    expect(t.path()).toBe('/workplaces')
  })
})

describe('create a workplace', () => {
  it('requires name, kind of business, city and state', async () => {
    const t = setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'Create workplace' }))
    expect(screen.getByText('Give your workplace a name.')).toBeTruthy()
    expect(screen.getByText('Pick the closest match.')).toBeTruthy()
    expect(screen.getByText('Enter the city.')).toBeTruthy()
    expect(screen.getByText('Pick the state.')).toBeTruthy()
    expect(t.calls.some((c) => c.url === '/api/stores')).toBe(false)
  })

  it('POSTs the basics with template empty and opens /w/:id', async () => {
    const t = setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    type('Name', 'Harbor Grill')
    fireEvent.click(screen.getByLabelText('Restaurant / café'))
    type('City', 'Chicago')
    type('State', 'IL')
    type(/In a few words/, 'seafood grill, busy weekends')
    fireEvent.click(screen.getByRole('button', { name: 'Create workplace' }))

    await waitFor(() => expect(t.path()).toMatch(/^\/w\/mock-\d+$/))
    const req = t.calls.find((c) => c.url === '/api/stores' && c.method === 'POST')
    expect(req?.body).toEqual({
      template: 'empty',
      name: 'Harbor Grill',
      sector: 'food',
      business_description: 'seafood grill, busy weekends',
      jurisdiction: { state: 'IL', city: 'chicago' },
    })
    expect(await screen.findByText('Harbor Grill')).toBeTruthy()
    expect(screen.getByText('Chicago, IL')).toBeTruthy()

    // B3: the switcher lists it, checked, with + New workplace and Sign out.
    fireEvent.click(screen.getByRole('button', { name: 'My workplaces ▾' }))
    const item = await screen.findByRole('menuitemradio', { name: /Harbor Grill/ })
    expect(item.getAttribute('aria-checked')).toBe('true')
    expect(screen.getByRole('menuitem', { name: '+ New workplace' })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeTruthy()
  })

  it('"Or explore a sample workplace" opens a sample copy', async () => {
    const t = setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'Or explore a sample workplace' }))
    fireEvent.click(await screen.findByRole('button', { name: /Austin, TX/ }))
    await waitFor(() => expect(t.path()).toMatch(/^\/w\/mock-\d+$/))
    expect(t.calls.find((c) => c.url === '/api/workplaces/sample')?.body).toEqual({ template: 'demo' })
    expect(await screen.findByText(/^Sample: /)).toBeTruthy()
  })
})

async function createHarborGrill() {
  await signUp()
  await screen.findByRole('heading', { name: 'New workplace' })
  type('Name', 'Harbor Grill')
  fireEvent.click(screen.getByLabelText('Restaurant / café'))
  type('City', 'Chicago')
  type('State', 'IL')
  fireEvent.click(screen.getByRole('button', { name: 'Create workplace' }))
}

describe('setup mode → workspace mode (B4)', () => {
  it('a new, empty workplace starts in setup mode and cannot be built yet', async () => {
    const t = setup('/signup')
    await createHarborGrill()

    // Setup mode: step tracker + centered chat, no tabs.
    const steps = await screen.findByRole('complementary', { name: 'Setup steps' })
    for (const label of ['Business', 'Hours & budget', 'Team', 'Staffing', 'Rules', 'Build'])
      expect(within(steps).getByText(label)).toBeTruthy()
    expect(screen.queryByRole('tablist')).toBeNull()
    expect(screen.getByLabelText('Business: not done')).toBeTruthy()
    expect(t.calls.find((c) => c.url === '/api/stores')?.body).toMatchObject({ template: 'empty' })

    // PUNCHLIST B4 QA: no people / training / staffing → Build is off, says what's missing, no "Build anyway".
    expect(
      await screen.findByText('To build a schedule, first add your team, who can work each role and how many people you need, and when.'),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Build my schedule' }).hasAttribute('disabled')).toBe(true)
    expect(screen.queryByRole('button', { name: 'Build anyway' })).toBeNull()
  })

  it('switches to the workspace after the first build, keeping the chat', async () => {
    setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'Or explore a sample workplace' }))
    fireEvent.click(await screen.findByRole('button', { name: /Austin, TX/ }))
    await screen.findByRole('complementary', { name: 'Setup steps' })
    expect(screen.queryByRole('tablist')).toBeNull()

    // Talk to the chat first; the conversation must survive the mode switch.
    fireEvent.click(screen.getByRole('button', { name: 'Set up my store' }))
    await screen.findByText(/Let's start with the store itself/)

    // The sample has a team, training and staffing, so Build (or "Build anyway") is on.
    const build = await waitFor(() => {
      const b = screen.queryByRole('button', { name: 'Build anyway' }) ?? screen.getByRole('button', { name: 'Build my schedule' })
      expect(b.hasAttribute('disabled')).toBe(false)
      return b
    })
    fireEvent.click(build)
    await screen.findByRole('tablist', { name: 'Views' }, { timeout: 5000 })
    expect(screen.queryByRole('complementary', { name: 'Setup steps' })).toBeNull()

    // The chat is now a drawer behind "Ask Shiftwright", with the same conversation.
    expect(screen.queryByText(/Let's start with the store itself/)).toBeTruthy()
    const ask = screen.getByRole('button', { name: 'Ask Shiftwright' })
    expect(ask.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(ask)
    expect(ask.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('region', { name: 'Chat' })).toBeTruthy()

    // B5: four tabs; coverage is a toggle inside Schedule; Team & rules carries the rulebook.
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Schedule', 'Call-outs', 'Team & rules', 'Compliance'])
    fireEvent.click(screen.getByRole('button', { name: 'Coverage by hour' }))
    expect(screen.getByRole('button', { name: 'Coverage by hour' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('tab', { name: 'Team & rules' }))
    expect(screen.getByRole('complementary', { name: 'Rules' })).toBeTruthy()
  })
})

describe('sample business (B7)', () => {
  it('one click on Restaurant sets itself up; the user only answers the decision card, then builds', async () => {
    const t = setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: /^Restaurant/ }))
    await waitFor(() => expect(t.path()).toMatch(/^\/w\/mock-\d+$/))
    expect(t.calls.find((c) => c.url === '/api/workplaces/generated')?.body).toEqual({ sector: 'food', size: 'S', difficulty: 'easy' })

    // Setup mode, manager's message already sent with its files, autopilot on.
    await screen.findByRole('complementary', { name: 'Setup steps' })
    expect(await screen.findByRole('list', { name: 'Attached files' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Autopilot on · Pause' })).toBeTruthy()

    // The only stop: the equipment-tags decision.
    await screen.findByText('Check the equipment tags', {}, { timeout: 5000 })
    fireEvent.click(screen.getByLabelText('Keep tags'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    // Routine cards after it go through on their own, then the agent offers the build.
    await screen.findByText('Setup is done. Build the week now?', {}, { timeout: 5000 })
    const chat = screen.getByRole('region', { name: 'Chat' })
    fireEvent.click(within(chat).getByRole('button', { name: 'Build my schedule' }))
    await screen.findByRole('tablist', { name: 'Views' }, { timeout: 5000 })
  }, 20000)

  it('More options sends size, difficulty, location and seed', async () => {
    const t = setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'More options' }))
    fireEvent.change(screen.getByLabelText('Seed (optional)'), { target: { value: '42' } })
    fireEvent.change(screen.getByLabelText('Size'), { target: { value: 'M' } })
    fireEvent.click(screen.getByLabelText('Legal traps'))
    fireEvent.click(screen.getByRole('button', { name: /^Retail store/ }))
    await waitFor(() => expect(t.path()).toMatch(/^\/w\//))
    expect(t.calls.find((c) => c.url === '/api/workplaces/generated')?.body).toEqual({ sector: 'retail', size: 'M', difficulty: 'legal_trap', seed: 42 })
  })
})

describe('decisions waiting (C3)', () => {
  it('opens the chat drawer and focuses the message box', async () => {
    setup('/signup')
    await signUp()
    await screen.findByRole('heading', { name: 'New workplace' })
    fireEvent.click(screen.getByRole('button', { name: 'Or explore a sample workplace' }))
    fireEvent.click(await screen.findByRole('button', { name: /Austin, TX/ }))
    await screen.findByRole('complementary', { name: 'Setup steps' })
    const build = await waitFor(() => {
      const b = screen.queryByRole('button', { name: 'Build anyway' }) ?? screen.getByRole('button', { name: 'Build my schedule' })
      expect(b.hasAttribute('disabled')).toBe(false)
      return b
    })
    fireEvent.click(build)
    await screen.findByRole('tablist', { name: 'Views' }, { timeout: 5000 })

    const ask = screen.getByRole('button', { name: 'Ask Shiftwright' })
    expect(ask.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(await screen.findByRole('button', { name: /^\d+ decisions? waiting$/ }))
    expect(ask.getAttribute('aria-expanded')).toBe('true')
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Message')))
  })
})
