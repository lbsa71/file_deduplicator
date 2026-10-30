import React, { useEffect, useState, useId } from "react";
import * as Slider from "@radix-ui/react-slider";
import { normalizeFilters, filterChips } from "./query.js";
import "./filters.css";

function LabelChoices({
  title,
  values = [],
  selected = [],
  onChange,
  children,
}) {
  const [search, setSearch] = useState("");
  const id = useId();
  const options = new Map(values.map((v) => [v.value, v.count]));
  for (const value of selected) if (!options.has(value)) options.set(value, 0);
  const rows = [...options].sort(([a], [b]) => a.localeCompare(b));
  return (
    <fieldset className="facet-labels">
      <legend className="sr-only">{title}</legend>
      {children}
      {rows.length > 6 && (
        <input
          type="search"
          value={search}
          placeholder={`Find ${title.toLowerCase()}`}
          aria-label={`Find ${title.toLowerCase()}`}
          onChange={(e) => setSearch(e.target.value)}
        />
      )}
      <div className="facet-options">
        {rows
          .filter(
            ([value]) =>
              selected.includes(value) ||
              value.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
          )
          .map(([value, count], index) => (
            <label
              key={value}
              htmlFor={`${id}-${index}`}
              className="facet-option"
            >
              <input
                type="checkbox"
                id={`${id}-${index}`}
                checked={selected.includes(value)}
                onChange={() =>
                  onChange(
                    selected.includes(value)
                      ? selected.filter((v) => v !== value)
                      : [...selected, value],
                  )
                }
              />
              <span>{value}</span>
              <small>{count.toLocaleString()}</small>
            </label>
          ))}
        {!rows.length && (
          <p className="facet-empty">
            No {title.toLowerCase()} labels in this selection.
          </p>
        )}
      </div>
    </fieldset>
  );
}

function DateFilter({ filters, facets, change }) {
  const [bounds, setBounds] = useState([filters.from || "", filters.to || ""]);
  const [rangeDraft, setRangeDraft] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setBounds([filters.from || "", filters.to || ""]);
    setError("");
    setRangeDraft(null);
  }, [filters.from, filters.to, filters.date]);
  const years = (facets.years || [])
    .map((row) => ({ year: Number(row.value), count: row.count }))
    .filter((row) => Number.isInteger(row.year) && row.year > 0);
  const chosen = [filters.from, filters.to]
    .filter(Boolean)
    .map((v) => Number(v.slice(0, 4)))
    .filter(Number.isFinite);
  const available = [...years.map((row) => row.year), ...chosen];
  const min = available.length ? Math.min(...available) : 0;
  const max = available.length ? Math.max(...available) : 0;
  const range = rangeDraft || [
    filters.from ? Number(filters.from.slice(0, 4)) : min,
    filters.to ? Number(filters.to.slice(0, 4)) : max,
  ];
  const maxCount = Math.max(1, ...years.map((row) => row.count));
  function yearRange([start, end]) {
    setRangeDraft(null);
    change({
      date: "known",
      from: `${String(start).padStart(4, "0")}-01-01`,
      to: `${String(end).padStart(4, "0")}-12-31`,
    });
  }
  function applyDates(e) {
    e.preventDefault();
    if (bounds[0] && bounds[1] && bounds[0] > bounds[1]) {
      setError("Start date must be before or equal to end date.");
      return;
    }
    setError("");
    change({
      from: bounds[0],
      to: bounds[1],
      date: bounds.some(Boolean) ? "known" : "any",
    });
  }
  return (
    <div className="facet-time">
      <label className="facet-control">
        Capture date
        <select
          aria-label="Capture date availability"
          value={filters.date || "any"}
          onChange={(e) =>
            change({
              date: e.target.value,
              ...(e.target.value !== "known" ? { from: "", to: "" } : {}),
            })
          }
        >
          <option value="any">Any date</option>
          <option value="known">Date known</option>
          <option value="unknown">
            Date unknown ({facets.date_unknown || 0})
          </option>
        </select>
      </label>
      {filters.date !== "unknown" && (
        <>
          {!!years.length && (
            <>
              <div
                className="date-histogram"
                aria-label="Photos by capture year"
                style={{
                  gridTemplateColumns: `repeat(${max - min + 1},minmax(0,1fr))`,
                }}
              >
                {years.map(({ year, count }) => (
                  <button
                    type="button"
                    key={year}
                    style={{ gridColumn: year - min + 1 }}
                    title={`${year}: ${count.toLocaleString()} photos. Filter to this year.`}
                    aria-label={`${year}, ${count.toLocaleString()} photos`}
                    aria-pressed={
                      filters.from === `${year}-01-01` &&
                      filters.to === `${year}-12-31`
                    }
                    onClick={() => yearRange([year, year])}
                  >
                    <span
                      style={{
                        height: `${Math.max(3, (count / maxCount) * 100)}%`,
                      }}
                      className={
                        year >= range[0] && year <= range[1]
                          ? "within-range"
                          : ""
                      }
                    />
                  </button>
                ))}
              </div>
              <div className="date-extents">
                <span>{min}</span>
                <span>{max}</span>
              </div>
              {max > min && (
                <Slider.Root
                  className="date-slider"
                  value={range}
                  min={min}
                  max={max}
                  step={1}
                  onValueChange={setRangeDraft}
                  onValueCommit={yearRange}
                >
                  <Slider.Track className="date-slider-track">
                    <Slider.Range className="date-slider-range" />
                  </Slider.Track>
                  <Slider.Thumb
                    className="date-slider-thumb"
                    aria-label="Start year"
                    aria-valuetext={String(range[0])}
                  />
                  <Slider.Thumb
                    className="date-slider-thumb"
                    aria-label="End year"
                    aria-valuetext={String(range[1])}
                  />
                </Slider.Root>
              )}
              <p className="date-selection">
                {range[0] === range[1] ? range[0] : `${range[0]}–${range[1]}`}{" "}
                <small>Drag to choose years</small>
              </p>
            </>
          )}
          <form className="date-fields" onSubmit={applyDates}>
            <label>
              From
              <input
                aria-label="Capture date from"
                type="date"
                value={bounds[0]}
                onChange={(e) => setBounds([e.target.value, bounds[1]])}
              />
            </label>
            <label>
              Through
              <input
                aria-label="Capture date through"
                type="date"
                value={bounds[1]}
                onChange={(e) => setBounds([bounds[0], e.target.value])}
              />
            </label>
            {error && (
              <p className="date-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit">Apply dates</button>
            {(filters.from || filters.to || filters.date) && (
              <button
                type="button"
                onClick={() => change({ from: "", to: "", date: "any" })}
              >
                Clear dates
              </button>
            )}
          </form>
        </>
      )}
    </div>
  );
}

export function Filters({ filters = {}, onChange, facets = {}, busy = false }) {
  const f = normalizeFilters(filters);
  const [open, setOpen] = useState(() =>
    typeof matchMedia === "function"
      ? matchMedia("(min-width: 1000px)").matches
      : true,
  );
  useEffect(() => {
    const media = matchMedia("(min-width: 1000px)");
    const changed = () => setOpen(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  const change = (patch) => onChange(normalizeFilters({ ...f, ...patch }));
  const active = filterChips(f).length;
  return (
    <details
      className="query-filters"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      aria-busy={busy}
    >
      <summary>
        Filters{active ? <span className="filter-badge">{active}</span> : null}
        <span className="filter-update">
          {busy ? "Updating…" : "Refine your library"}
        </span>
      </summary>
      <div className="filter-sections">
        <details className="filter-section" open>
          <summary>
            People{" "}
            <small>
              {(f.people || []).length ? `${f.people.length} selected` : ""}
            </small>
          </summary>
          <LabelChoices
            title="People"
            values={facets.people}
            selected={f.people}
            onChange={(people) => change({ people })}
          >
            <label className="facet-control">
              Match
              <select
                aria-label="People match mode"
                value={f.people_mode || "any"}
                onChange={(e) => change({ people_mode: e.target.value })}
              >
                <option value="any">Any selected person</option>
                <option value="all">All selected people</option>
              </select>
            </label>
            <p className="facet-help">
              {f.people_mode === "all"
                ? "Counts show matches with each additional person."
                : "Counts show each person with the other filters applied."}
            </p>
          </LabelChoices>
        </details>
        <details className="filter-section" open>
          <summary>
            Place{" "}
            <small>{f.place?.length ? `${f.place.length} selected` : ""}</small>
          </summary>
          <LabelChoices
            title="Place"
            values={facets.place}
            selected={f.place}
            onChange={(place) => change({ place })}
          >
            <p className="facet-help">
              Choose any city, region, country or continent. Multiple places
              match any selected location.
            </p>
          </LabelChoices>
        </details>
        <details className="filter-section" open>
          <summary>Time</summary>
          <DateFilter filters={f} facets={facets} change={change} />
        </details>
        <fieldset className="filter-section favorite-section">
          <legend>Favourites</legend>
          <div className="facet-segments">
            {[
              ["any", "Any"],
              ["yes", "Yes"],
              ["no", "No"],
            ].map(([value, label]) => (
              <label
                key={value}
                className={(f.favorite || "any") === value ? "selected" : ""}
              >
                <input
                  type="radio"
                  name="filter-favourite"
                  value={value}
                  checked={(f.favorite || "any") === value}
                  onChange={() => change({ favorite: value })}
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <details className="filter-section">
          <summary>
            Albums{" "}
            <small>
              {f.albums?.length ? `${f.albums.length} selected` : ""}
            </small>
          </summary>
          <LabelChoices
            title="Albums"
            values={facets.albums}
            selected={f.albums}
            onChange={(albums) => change({ albums })}
          />
        </details>
        <details className="filter-section">
          <summary>
            Tags{" "}
            <small>{f.tags?.length ? `${f.tags.length} selected` : ""}</small>
          </summary>
          <LabelChoices
            title="Tags"
            values={facets.tags}
            selected={f.tags}
            onChange={(tags) => change({ tags })}
          />
        </details>
        <details className="filter-section">
          <summary>More filters</summary>
          <label className="facet-control">
            Media type
            <select
              value={f.type || "any"}
              onChange={(e) => change({ type: e.target.value })}
            >
              <option value="any">Images and videos</option>
              <option value="image">Images</option>
              <option value="video">Videos</option>
            </select>
          </label>
          <label className="facet-control">
            Missing metadata
            <select
              value={f.missing || "any"}
              onChange={(e) => change({ missing: e.target.value })}
            >
              <option value="any">Any</option>
              <option value="people">No people labels</option>
              <option value="albums">No album labels</option>
              <option value="place">No place names</option>
              <option value="location">No resolved coordinates</option>
              <option value="location_conflict">Conflicting locations</option>
            </select>
          </label>
          <p className="facet-help">
            An unlabelled photo may still contain people.
          </p>
        </details>
        {active > 0 && (
          <button
            type="button"
            className="clear-filters"
            onClick={() => onChange({})}
          >
            Clear all filters
          </button>
        )}
      </div>
    </details>
  );
}

export function FilterChips({ filters = {}, onChange }) {
  const chips = filterChips(filters);
  if (!chips.length) return null;
  return (
    <div className="filter-chips" aria-label="Applied filters">
      {filters.people?.length > 1 && (
        <span className="people-match-summary">
          {filters.people_mode === "all"
            ? "All selected people"
            : "Any selected person"}
        </span>
      )}
      {chips.map((chip) => (
        <button
          type="button"
          key={chip.key}
          aria-label={`Remove filter ${chip.label}`}
          onClick={() => onChange(chip.filters)}
        >
          {chip.label}
          <span aria-hidden="true">×</span>
        </button>
      ))}
      <button
        type="button"
        className="clear-chips"
        onClick={() => onChange({})}
      >
        Clear filters
      </button>
    </div>
  );
}
