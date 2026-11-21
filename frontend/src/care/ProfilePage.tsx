// Care profile: personal info, emergency contacts, medical history,
// medications, allergies and care notes. DEMO DATA ONLY: never enter a real
// person's medical details.
import { useEffect, useState } from "react";
import { getJson, sendJson } from "../api";

interface Contact {
  name: string;
  relation: string;
  phone: string;
}
interface Medication {
  name: string;
  dose: string;
}
export interface Profile {
  name: string;
  age: number | null;
  address: string;
  contacts: Contact[];
  medical_history: string;
  medications: Medication[];
  allergies: string[];
  care_notes: string;
}
interface Stored {
  data: Profile;
  updated_at: string;
}

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [allergyText, setAllergyText] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    getJson<Stored>("/api/profile")
      .then((stored) => {
        setProfile(stored.data);
        setAllergyText(stored.data.allergies.join(", "));
      })
      .catch(() => setStatus("Couldn't load the profile. Is the backend running?"));
  }, []);

  if (!profile) return <p className="hint">{status || "Loading…"}</p>;

  const set = <K extends keyof Profile>(key: K, value: Profile[K]) =>
    setProfile({ ...profile, [key]: value });

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const body: Profile = {
      ...profile,
      allergies: allergyText.split(",").map((a) => a.trim()).filter(Boolean),
    };
    try {
      const stored = await sendJson<Stored>("/api/profile", "PUT", body);
      setProfile(stored.data);
      setStatus(`Saved at ${new Date(stored.updated_at).toLocaleTimeString()}`);
    } catch {
      setStatus("Save failed. Check the fields and try again.");
    }
  };

  const updateList = <T,>(list: T[], i: number, item: T) => list.map((x, j) => (j === i ? item : x));

  return (
    <form className="care-card profile" onSubmit={save}>
      <h2>Care profile</h2>
      <p className="hint warn">Demo data only. Don't enter real medical information.</p>

      <fieldset>
        <legend>Personal info</legend>
        <label>
          Name
          <input value={profile.name} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label>
          Age
          <input
            type="number"
            min={0}
            max={130}
            value={profile.age ?? ""}
            onChange={(e) => set("age", e.target.value === "" ? null : Number(e.target.value))}
          />
        </label>
        <label className="wide">
          Address
          <input value={profile.address} onChange={(e) => set("address", e.target.value)} />
        </label>
      </fieldset>

      <fieldset>
        <legend>Emergency contacts</legend>
        {profile.contacts.map((c, i) => (
          <div className="list-row" key={i}>
            <input
              aria-label="Contact name"
              placeholder="Name"
              value={c.name}
              onChange={(e) => set("contacts", updateList(profile.contacts, i, { ...c, name: e.target.value }))}
            />
            <input
              aria-label="Relation"
              placeholder="Relation"
              value={c.relation}
              onChange={(e) =>
                set("contacts", updateList(profile.contacts, i, { ...c, relation: e.target.value }))
              }
            />
            <input
              aria-label="Phone"
              placeholder="Phone"
              value={c.phone}
              onChange={(e) => set("contacts", updateList(profile.contacts, i, { ...c, phone: e.target.value }))}
            />
            {c.phone && (
              <a className="btn btn-small" href={`tel:${c.phone}`}>
                Call
              </a>
            )}
            <button
              type="button"
              className="btn btn-small"
              aria-label={`Remove ${c.name || "contact"}`}
              onClick={() => set("contacts", profile.contacts.filter((_, j) => j !== i))}
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn"
          onClick={() => set("contacts", [...profile.contacts, { name: "", relation: "", phone: "" }])}
        >
          Add contact
        </button>
      </fieldset>

      <fieldset>
        <legend>Medical</legend>
        <label className="wide">
          Medical history
          <textarea
            rows={3}
            value={profile.medical_history}
            onChange={(e) => set("medical_history", e.target.value)}
          />
        </label>
        <div className="wide">Medications</div>
        {profile.medications.map((m, i) => (
          <div className="list-row" key={i}>
            <input
              aria-label="Medication"
              placeholder="Medication"
              value={m.name}
              onChange={(e) =>
                set("medications", updateList(profile.medications, i, { ...m, name: e.target.value }))
              }
            />
            <input
              aria-label="Dose"
              placeholder="Dose / schedule"
              value={m.dose}
              onChange={(e) =>
                set("medications", updateList(profile.medications, i, { ...m, dose: e.target.value }))
              }
            />
            <button
              type="button"
              className="btn btn-small"
              aria-label={`Remove ${m.name || "medication"}`}
              onClick={() => set("medications", profile.medications.filter((_, j) => j !== i))}
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn"
          onClick={() => set("medications", [...profile.medications, { name: "", dose: "" }])}
        >
          Add medication
        </button>
        <label className="wide">
          Allergies (comma separated)
          <input value={allergyText} onChange={(e) => setAllergyText(e.target.value)} />
        </label>
      </fieldset>

      <fieldset>
        <legend>Care notes</legend>
        <label className="wide">
          <textarea rows={4} value={profile.care_notes} onChange={(e) => set("care_notes", e.target.value)} />
        </label>
      </fieldset>

      <div className="row">
        <button type="submit" className="btn btn-primary">
          Save
        </button>
        <span role="status" className="hint">
          {status}
        </span>
      </div>
    </form>
  );
}
