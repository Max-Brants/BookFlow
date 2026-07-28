import { Link } from 'react-router-dom';

import { withBasePath } from '../../utils/basePath';

type PosterBadgeTone = 'violet' | 'green' | 'blue';

interface PosterCardProps {
  to: string;
  title: string;
  author?: string | null;
  coverUrl?: string | null;
  badge?: string;
  badgeTone?: PosterBadgeTone;
  progress?: number;
}

const BADGE_CLASSES: Record<PosterBadgeTone, string> = {
  violet: 'bg-violet-600 text-white',
  green: 'bg-emerald-500 text-white',
  blue: 'bg-blue-600 text-white',
};

export const PosterCard = ({
  to,
  title,
  author,
  coverUrl,
  badge,
  badgeTone = 'violet',
  progress,
}: PosterCardProps) => {
  const accessibleName = author ? `${title}, ${author}` : title;
  return (
    <Link
      to={to}
      aria-label={accessibleName}
      title={accessibleName}
      className="group relative w-28 shrink-0 snap-start overflow-hidden rounded-xl border border-(--border-muted) bg-(--bg-soft) shadow-lg transition duration-200 hover:-translate-y-1 hover:border-violet-500/60 focus-visible:-translate-y-1 focus-visible:ring-2 focus-visible:ring-violet-500 sm:w-[7.5rem]"
    >
      {coverUrl ? (
        <img
          src={withBasePath(coverUrl)}
          alt=""
          loading="lazy"
          className="aspect-[2/3] w-full object-cover"
        />
      ) : (
        <div className="flex aspect-[2/3] w-full items-center justify-center bg-linear-to-br from-violet-700 via-indigo-800 to-slate-950 px-3 text-center text-lg font-bold text-white">
          {title}
        </div>
      )}

      {badge && (
        <span
          className={`absolute top-2 left-2 rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide ${BADGE_CLASSES[badgeTone]}`}
        >
          {badge}
        </span>
      )}

      <div className="absolute inset-x-0 bottom-0 translate-y-2 bg-linear-to-t from-black via-black/75 to-transparent px-3 pt-12 pb-3 text-white opacity-0 transition duration-200 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100">
        <p className="line-clamp-2 text-sm font-semibold">{title}</p>
        {author && <p className="mt-0.5 truncate text-xs text-slate-300">{author}</p>}
      </div>

      {typeof progress === 'number' && (
        <div className="absolute right-0 bottom-0 left-0 h-1.5 bg-black/55">
          <div
            className="h-full bg-linear-to-r from-violet-500 to-sky-400"
            style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
          />
        </div>
      )}
    </Link>
  );
};
