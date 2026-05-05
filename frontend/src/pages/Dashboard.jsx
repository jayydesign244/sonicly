import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Waveform from '../components/Waveform'
import { useAuth } from '../context/AuthContext'

const PROJECTS = [
  { id: 1, name: 'podcast_episode_12', duration: '3:42', edited: '2 hours ago', status: 'In Progress', seed: 42 },
  { id: 2, name: 'interview_sarah_may', duration: '18:04', edited: 'Yesterday', status: 'Exported', seed: 77 },
  { id: 3, name: 'webinar_recording_q2', duration: '54:11', edited: '3 days ago', status: 'Exported', seed: 13 },
  { id: 4, name: 'voice_memo_ideas', duration: '0:52', edited: '5 days ago', status: 'New', seed: 55 },
  { id: 5, name: 'client_call_acme', duration: '22:18', edited: 'Last week', status: 'In Progress', seed: 88 },
  { id: 6, name: 'product_demo_v2', duration: '7:30', edited: 'Last week', status: 'New', seed: 31 },
]

const STATUS_STYLE = {
  'In Progress': 'bg-orange-50 text-orange-600 border-orange-100',
  'Exported': 'bg-emerald-50 text-emerald-600 border-emerald-100',
  'New': 'bg-gray-100 text-gray-500 border-gray-200',
}

function ThreeDotMenu({ onRename, onDuplicate, onDelete }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative" onClick={e => e.stopPropagation()}>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="5" cy="12" r="2" />
          <circle cx="12" cy="12" r="2" />
          <circle cx="19" cy="12" r="2" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-8 z-20 card shadow-modal w-36 py-1 animate-fade-in">
            {[
              { label: 'Rename', action: onRename },
              { label: 'Duplicate', action: onDuplicate },
              { label: 'Delete', action: onDelete, danger: true },
            ].map(({ label, action, danger }) => (
              <button
                key={label}
                onClick={() => { action?.(); setOpen(false) }}
                className={`w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 transition-colors ${danger ? 'text-red-500 hover:bg-red-50' : 'text-gray-700'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ProjectCard({ project, onClick }) {
  return (
    <div
      onClick={onClick}
      className="card p-4 cursor-pointer hover:shadow-card-hover hover:border-gray-300 transition-all duration-150 group animate-fade-in"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <Waveform seed={project.seed} height={32} bars={48} color="#6366f1" />
        </div>
        <ThreeDotMenu
          onRename={() => {}}
          onDuplicate={() => {}}
          onDelete={() => {}}
        />
      </div>

      <div className="space-y-1.5">
        <p className="text-sm font-semibold text-gray-900 truncate group-hover:text-accent-600 transition-colors">
          {project.name}
        </p>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>{project.duration}</span>
          <span>·</span>
          <span>Edited {project.edited}</span>
        </div>
        <div>
          <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full border ${STATUS_STYLE[project.status]}`}>
            {project.status}
          </span>
        </div>
      </div>
    </div>
  )
}

function NewProjectModal({ onClose, onStart }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card shadow-modal w-full max-w-md p-6 animate-slide-up">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-gray-900">Start a new project</h2>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-gray-100 text-gray-400">
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1.5">Project name</label>
          <input
            type="text"
            className="input-field mb-5"
            defaultValue="Untitled Project"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={onStart}
            className="flex flex-col items-center gap-2.5 p-5 border-2 border-gray-200 hover:border-accent-400 hover:bg-accent-50 rounded-xl transition-colors group"
          >
            <div className="w-10 h-10 bg-gray-100 group-hover:bg-accent-100 rounded-xl flex items-center justify-center text-gray-500 group-hover:text-accent-500 transition-colors">
              <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
            </div>
            <div className="text-center">
              <div className="text-sm font-medium text-gray-900">Upload a file</div>
              <div className="text-xs text-gray-400 mt-0.5">MP3, WAV, M4A, FLAC</div>
            </div>
          </button>

          <button
            onClick={onStart}
            className="flex flex-col items-center gap-2.5 p-5 border-2 border-gray-200 hover:border-accent-400 hover:bg-accent-50 rounded-xl transition-colors group"
          >
            <div className="w-10 h-10 bg-gray-100 group-hover:bg-accent-100 rounded-xl flex items-center justify-center text-gray-500 group-hover:text-accent-500 transition-colors">
              <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <div className="text-center">
              <div className="text-sm font-medium text-gray-900">Record audio</div>
              <div className="text-xs text-gray-400 mt-0.5">Record in the browser</div>
            </div>
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { user, signOut } = useAuth()
  const [showNewProject, setShowNewProject] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)
  const [search, setSearch] = useState('')

  const displayName = user?.user_metadata?.name || user?.email?.split('@')[0] || 'You'
  const initials = displayName.split(' ').map(s => s[0]).slice(0, 2).join('').toUpperCase()

  const handleSignOut = async () => {
    await signOut()
    navigate('/')
  }

  const filtered = PROJECTS.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  )

  const handleProjectClick = (project) => {
    navigate('/processing', { state: { project } })
  }

  const handleNewProjectStart = () => {
    setShowNewProject(false)
    navigate('/processing', { state: { project: { id: 99, name: 'Untitled Project', duration: '0:00', seed: 64 } } })
  }

  return (
    <div className="min-h-screen bg-surface flex">
      {/* Sidebar */}
      <aside className="w-[220px] flex-shrink-0 border-r border-gray-200 bg-white flex flex-col h-screen sticky top-0">
        {/* Logo */}
        <div className="h-14 px-4 flex items-center border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-accent-500 rounded-md flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 20 20" fill="white">
                <rect x="1" y="8" width="2.5" height="4" rx="1.25" />
                <rect x="5" y="5" width="2.5" height="10" rx="1.25" />
                <rect x="9" y="3" width="2.5" height="14" rx="1.25" />
                <rect x="13" y="6" width="2.5" height="8" rx="1.25" />
                <rect x="17" y="8" width="2.5" height="4" rx="1.25" />
              </svg>
            </div>
            <span className="font-semibold text-gray-900 text-sm">Sonicly</span>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          <div className="sidebar-link-active">
            <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
            Dashboard
          </div>
          <div className="sidebar-link">
            <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Recent
          </div>
          <div className="sidebar-link">
            <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
            Starred
          </div>

          <div className="border-t border-gray-100 my-3" />

          <button
            onClick={() => setShowNewProject(true)}
            className="w-full flex items-center justify-center gap-2 bg-accent-500 hover:bg-accent-600 text-white text-sm font-medium px-3 py-2 rounded-lg transition-colors"
          >
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Project
          </button>
        </nav>

        {/* User */}
        <div className="border-t border-gray-100 px-3 py-3 relative">
          {showUserMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowUserMenu(false)} />
              <div className="absolute bottom-14 left-3 right-3 z-20 card shadow-modal py-1 animate-fade-in">
                <button
                  onClick={handleSignOut}
                  className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Sign out
                </button>
              </div>
            </>
          )}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-7 h-7 bg-accent-100 text-accent-600 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0">
                {initials}
              </div>
              <span className="text-xs font-medium text-gray-700 truncate">{displayName}</span>
            </div>
            <button
              onClick={() => setShowUserMenu(v => !v)}
              className="text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
            >
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-h-screen">
        {/* Top bar */}
        <div className="h-14 border-b border-gray-200 bg-white px-6 flex items-center justify-between sticky top-0 z-10">
          <h1 className="text-sm font-semibold text-gray-900">My Projects</h1>
          <div className="flex items-center gap-3">
            <div className="relative">
              <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search projects..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent-500 focus:border-transparent w-48"
              />
            </div>
            <select className="text-xs text-gray-600 border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-accent-500">
              <option>Sort by: Last edited</option>
              <option>Sort by: Name</option>
              <option>Sort by: Duration</option>
            </select>
          </div>
        </div>

        <div className="p-6">
          {filtered.length === 0 ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
                <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} className="text-gray-400">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-gray-900 mb-1">No projects yet</h3>
              <p className="text-sm text-gray-400 mb-6">Upload an audio file or start recording to get started.</p>
              <div className="flex items-center gap-3">
                <button onClick={() => setShowNewProject(true)} className="btn-primary">Upload a file</button>
                <button onClick={() => setShowNewProject(true)} className="btn-ghost">Start recording</button>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4 xl:grid-cols-3 lg:grid-cols-2">
              {filtered.map(project => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onClick={() => handleProjectClick(project)}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      {showNewProject && (
        <NewProjectModal
          onClose={() => setShowNewProject(false)}
          onStart={handleNewProjectStart}
        />
      )}
    </div>
  )
}
